"""Runtime verification for unused_attributes.

Only *candidate* classes (those that, per the AST pass, write at least one
attribute) are instrumented.  Instrumentation is triggered lazily by
``sys.monitoring`` CALL events -- patching a class when it is instantiated
or when one of its methods is first called -- and eagerly by a meta-path
import hook for module-level classes.  Monitoring disables itself once
every pending candidate has been seen, so steady-state overhead is a
single WeakKeyDictionary probe per Python call.
"""
from __future__ import annotations

import atexit
import importlib.abc
import os
import sys
import weakref
from dataclasses import dataclass, field

from . import _hot
from ._static import Analysis, ClassInfo

_EVENTS = sys.monitoring.events
_MISSING = sys.monitoring.MISSING


def _norm_display(name: str) -> str:
    """'_Cls__attr' (mangled runtime name) -> '__attr' (source form)."""
    if name.startswith("_") and not name.startswith("__") \
            and "__" in name[1:]:
        return "__" + name.split("__", 1)[1]
    return name


@dataclass
class _Record:
    cls: type
    counts: dict
    sites: dict
    instantiated: bool = False


@dataclass
class Report:
    """Aggregated findings; produced once by Tracker.finish()."""
    lines: list[str] = field(default_factory=list)        # "file:line: W001: ..." strings, sorted
    uninstantiated: list[str] = field(default_factory=list)  # instrumented classes with no usage
    unexercised: list[str] = field(default_factory=list)  # pending classes never seen at all


class _CandidateFinder(importlib.abc.MetaPathFinder):
    """Import hook: patch candidate classes right after their module loads."""

    def __init__(self, tracker):
        self.tracker = tracker

    def find_spec(self, fullname, path=None, target=None):
        if fullname not in self.tracker._by_module:
            return None
        spec = None
        for finder in sys.meta_path:
            if finder is self:
                continue
            try:
                spec = finder.find_spec(fullname, path, target)
            except Exception:  # noqa: BLE001 - third-party finders may raise anything; never break import
                try:
                    spec = finder.find_spec(fullname, path)
                except Exception:  # noqa: BLE001
                    spec = None
            if spec is not None:
                break
        if spec is None or spec.loader is None:
            return spec
        orig_exec = spec.loader.exec_module

        def exec_module(module, _orig=orig_exec, _name=fullname):
            _orig(module)
            self.tracker.patch_module(_name, module)

        try:
            spec.loader.exec_module = exec_module
        except (AttributeError, TypeError):
            pass
        return spec


class Tracker:
    def __init__(self, analysis: Analysis, script_module: str = "__main__",
                 verbose: bool = False):
        self.verbose = verbose
        self._script_module = script_module
        # only dynamically-discovered write sites under the analyzed root are
        # meaningful; foreign frames (library base classes) are ignored
        self._root_prefix = os.path.join(analysis.root, "") \
            if analysis.root else ""
        self.pending: dict[tuple[str, str], ClassInfo] = analysis.candidates()
        # alias the script's classes under __main__ (runpy sets __module__)
        self._twin: dict[tuple[str, str], tuple[str, str]] = {}
        for (module, qualname), info in list(self.pending.items()):
            if module == script_module:
                alias = ("__main__", qualname)
                self.pending[alias] = info
                self._twin[alias] = (module, qualname)
                self._twin[(module, qualname)] = alias
        # (abs file path, qualname) -> pending key; robust against unusual
        # import names (pytest modules, importlib file loads, __main__).
        # Note a bare-qualname fallback would mis-patch same-named classes
        # in unrelated packages -- file matching is the safe fallback.
        self._by_file: dict[tuple[str, str], tuple[str, str]] = {}
        for key, info in self.pending.items():
            self._by_file[(os.path.abspath(info.file), key[1])] = key
        self._by_module: dict[str, list[tuple[str, str]]] = {}
        for key in self.pending:
            if key[0] != "__main__":
                self._by_module.setdefault(key[0], []).append(key)
        self._method_owners: dict[str, tuple[str, str]] = {}
        for key, info in self.pending.items():
            for mq in info.method_qualnames:
                self._method_owners.setdefault(mq, key)
        # cls -> _Record for instrumented classes, cls -> None once decided
        # irrelevant; a single WeakKeyDictionary probe per monitored call
        self._state: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
        self.records: list[_Record] = []
        self._finder = _CandidateFinder(self)
        self._tool_id: int | None = None
        self._started = False
        self._result: Report | None = None

    # ---- class matching -------------------------------------------------

    @staticmethod
    def _key(klass) -> tuple[str, str]:
        return (getattr(klass, "__module__", "") or "",
                getattr(klass, "__qualname__", "") or "")

    def _info_for(self, cls):
        """(matched pending key, ClassInfo) for cls, or (None, None)."""
        key = self._key(cls)
        info = self.pending.get(key)
        if info is not None:
            return key, info
        # fall back to matching the class's source file
        module = sys.modules.get(key[0])
        path = getattr(module, "__file__", None) if module else None
        if path:
            fkey = self._by_file.get((os.path.abspath(path), key[1]))
            if fkey is not None:
                info = self.pending.get(fkey)
                if info is not None:
                    return fkey, info
        return None, None

    def _mro_has_pending(self, cls) -> bool:
        try:
            mro = cls.__mro__
        except AttributeError:
            return False
        for base in mro[1:]:
            key, _ = self._info_for(base)
            if key is not None:
                return True
        return False

    def _resolve(self, key):
        """Locate a pending class object via sys.modules + qualname walk."""
        module = sys.modules.get(key[0])
        if module is None:
            return None
        obj = module
        for part in key[1].split("."):
            if part == "<locals>":
                return None
            obj = getattr(obj, part, None)
            if obj is None:
                return None
        return obj if isinstance(obj, type) else None

    # ---- patching --------------------------------------------------------

    def _seed(self, cls):
        """counts/sites dicts for cls, merged from pending MRO classes."""
        counts: dict = {}
        sites: dict = {}
        for base in reversed(getattr(cls, "__mro__", (cls,))):
            _, bi = self._info_for(base)
            if bi is not None:
                for name, site in bi.written.items():
                    counts[name] = 1 if name in bi.statically_read else 0
                    sites[name] = (site.file, site.line, site.display,
                                   bi.qualname)
        return counts, sites

    def _pop_key(self, matched_key):
        self.pending.pop(matched_key, None)
        twin = self._twin.get(matched_key)
        if twin is not None:
            self.pending.pop(twin, None)
        if not self.pending:
            self._disable()

    def _patch(self, cls, instantiated: bool):
        matched_key, _ = self._info_for(cls)
        counts, sites = self._seed(cls)
        owner = getattr(cls, "__qualname__", getattr(cls, "__name__", "?"))
        if not _hot.install(cls, counts, sites, owner, self._root_prefix):
            # cannot instrument this class; do not keep waiting for it
            if matched_key is not None:
                self._pop_key(matched_key)
            return None
        rec = _Record(cls=cls, counts=counts, sites=sites,
                      instantiated=instantiated)
        self._state[cls] = rec
        self.records.append(rec)
        if matched_key is not None:
            self._pop_key(matched_key)
        return rec

    def _consider(self, cls):
        try:
            state = self._state[cls]
        except KeyError:
            pass
        else:
            if state is not None:
                state.instantiated = True
            return
        self._state[cls] = None
        _, info = self._info_for(cls)
        if info is not None or self._mro_has_pending(cls):
            self._patch(cls, instantiated=True)

    def patch_module(self, module_name: str, module):
        """Called after a candidate-bearing module finishes importing."""
        for key in self._by_module.get(module_name, []):
            if key not in self.pending:
                continue
            cls = self._resolve(key)
            if cls is None or cls in self._state:
                continue
            if self._info_for(cls)[0] is None and \
                    not self._mro_has_pending(cls):
                self._state[cls] = None
                continue
            self._patch(cls, instantiated=False)
        if not self.pending:
            self._disable()

    # ---- monitoring ------------------------------------------------------

    def _on_call(self, code, offset, callable_, arg0):
        if isinstance(callable_, type):
            self._consider(callable_)               # C(...)
            recv = None
        else:
            recv = getattr(callable_, "__self__", None)
        if recv is not None:
            # bound method: receiver is the instance or the class (classmethod)
            self._consider(recv if isinstance(recv, type) else type(recv))
        elif arg0 is not _MISSING:
            if isinstance(arg0, type):
                self._consider(arg0)                # classmethod-style
            else:
                self._consider(type(arg0))          # method / plain call
        if self._method_owners:
            self._consider_method_owner(callable_, arg0)

    def _consider_method_owner(self, callable_, arg0):
        """staticmethod calls carry neither self nor cls; resolve the owner
        via the callable's qualname and mark it exercised."""
        q = getattr(callable_, "__qualname__", None)
        if q is None:
            func = getattr(callable_, "__func__", None)
            q = getattr(func, "__qualname__", None)
        owner_key = self._method_owners.get(q) if q else None
        if owner_key is None:
            return
        owner = self._resolve(owner_key)
        if owner is None:
            twin = self._twin.get(owner_key)
            if twin is not None:
                owner = self._resolve(twin)
        if owner is None:
            return
        try:
            static_call = (arg0 is _MISSING
                           or isinstance(arg0, type)
                           or not isinstance(arg0, owner))
        except TypeError:
            static_call = False
        if static_call:
            self._consider(owner)

    def start(self, register_exit: bool = True):
        if self._started:
            return
        self._started = True
        # patch candidates whose modules are already imported
        for module_name in list(self._by_module):
            module = sys.modules.get(module_name)
            if module is not None:
                self.patch_module(module_name, module)
        sys.meta_path.insert(0, self._finder)
        if self.pending:
            for tool_id in (5, 4, 3, 2, 1, 0):
                try:
                    sys.monitoring.use_tool_id(tool_id, "unused_attributes")
                except ValueError:
                    continue
                self._tool_id = tool_id
                break
            if self._tool_id is not None:
                sys.monitoring.register_callback(
                    self._tool_id, _EVENTS.CALL, self._on_call)
                sys.monitoring.set_events(self._tool_id, _EVENTS.CALL)
        if register_exit:
            atexit.register(self.report)

    def _disable(self):
        if self._tool_id is not None:
            try:
                sys.monitoring.set_events(self._tool_id, 0)
                sys.monitoring.register_callback(
                    self._tool_id, _EVENTS.CALL, None)
                sys.monitoring.free_tool_id(self._tool_id)
            except Exception:  # noqa: BLE001, S110 - teardown must never crash interpreter exit
                pass
            self._tool_id = None
        try:
            sys.meta_path.remove(self._finder)
        except ValueError:
            pass

    # ---- report ----------------------------------------------------------

    def finish(self) -> Report:
        """Stop tracking and aggregate findings.  Idempotent."""
        self._disable()
        if self._result is not None:
            return self._result
        # An attribute defined at a given site is "used" if it was read on
        # ANY patched class (e.g. a base-class attribute read through a
        # subclass instance).  Sites converge because the runtime write site
        # inside A.__init__ matches the AST definition site regardless of the
        # actual instance class.  Aggregate max counts per (file, line, name).
        totals: dict[tuple, int] = {}
        best_site: dict[tuple, tuple] = {}
        skipped = []
        for rec in self.records:
            cname = getattr(rec.cls, "__qualname__", repr(rec.cls))
            if not rec.instantiated:
                skipped.append(cname)
                continue
            for name, count in rec.counts.items():
                site = rec.sites.get(name, ("?", 0, name, cname))
                # normalize mangled runtime names ("_Cls__x") to the source
                # form ("__x") so AST and dynamic sites merge
                key = (site[0], site[1], _norm_display(site[2]))
                totals[key] = max(totals.get(key, 0), count)
                # prefer the unmangled display name when merging sites
                if (key not in best_site
                        or len(site[2]) < len(best_site[key][2])):
                    best_site[key] = site
        lines = []
        for key, total in totals.items():
            if total == 0:
                f, l, display, owner = best_site[key]
                lines.append(f"{f}:{l}: W001: in class {owner} "
                             f"attribute '{display}' was never read")
        unexercised = sorted({f"{m}.{q}" for m, q in self.pending})
        self._result = Report(lines=sorted(lines),
                              uninstantiated=skipped,
                              unexercised=unexercised)
        return self._result

    def report(self):
        result = self.finish()
        for line in result.lines:
            print(line, flush=True)
        if result.uninstantiated and self.verbose:
            print(f"note: {len(result.uninstantiated)} instrumented "
                  f"class(es) were never instantiated: "
                  f"{', '.join(result.uninstantiated)}", file=sys.stderr)
        if result.unexercised:
            print(f"note: {len(result.unexercised)} candidate class(es) were "
                  f"never exercised; their attributes were not checked",
                  file=sys.stderr)
            if self.verbose:
                for name in result.unexercised:
                    print(f"  {name}", file=sys.stderr)
