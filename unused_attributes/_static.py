"""Static (AST) analysis for unused_attributes.

Enumerates, per class:
  * attributes that are *written*      (self.x = ..., cls.x = ..., class-level x = ...)
  * attributes that are provably *read* (self.x loads, getattr(self, 'x'), super().x,
                                         self.__dict__ / vars(self) bulk introspection)

The runtime pass then only has to verify the remaining candidates.
"""
from __future__ import annotations

import ast
import os
from dataclasses import dataclass, field

_SKIP_DIRS = {
    ".git", ".hg", ".svn", ".tox", ".nox", ".venv", "venv", "env",
    "__pycache__", "node_modules", "site-packages", "dist", "build",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".idea", ".eggs",
}

_BULK_INTROSPECTION = {
    "vars", "dir", "asdict", "astuple", "fields", "getmembers",
    "getmembers_static", "is_dataclass", "model_dump", "dict",
}


def _mangle(class_name: str, attr: str) -> str:
    """Reproduce Python's __attr -> _Class__attr name mangling."""
    if attr.startswith("__") and not attr.endswith("__"):
        return f"_{class_name.lstrip('_')}{attr}"
    return attr


@dataclass
class AttrSite:
    file: str
    line: int
    display: str          # attribute name as written in the source
    class_level: bool = False


@dataclass
class ClassInfo:
    module: str
    qualname: str
    file: str
    line: int
    written: dict[str, AttrSite] = field(default_factory=dict)  # key: mangled name
    statically_read: set[str] = field(default_factory=set)      # mangled names
    method_qualnames: set[str] = field(default_factory=set)
    bulk_introspected: bool = False  # vars(self) / self.__dict__ / asdict(self) seen
    is_dataclass: bool = False

    @property
    def key(self) -> tuple[str, str]:
        return (self.module, self.qualname)


@dataclass
class Analysis:
    root: str = ""
    classes: dict[str, dict[str, ClassInfo]] = field(default_factory=dict)
    global_attr_reads: set[str] = field(default_factory=set)

    def candidates(self) -> dict[tuple[str, str], ClassInfo]:
        """Classes that have at least one written attribute."""
        out = {}
        for module_classes in self.classes.values():
            for info in module_classes.values():
                if info.written:
                    out[info.key] = info
        return out


class _Visitor(ast.NodeVisitor):
    def __init__(self, module: str, filename: str):
        self.module = module
        self.filename = filename
        # scope stack entries: dict(kind='module'|'class'|'func', name=..., ...)
        self.stack: list[dict] = [{"kind": "module", "name": module,
                                   "self_name": None, "self_owner": None}]
        self.qual_parts: list[str] = []
        self.classes: dict[str, ClassInfo] = {}
        self.global_reads: set[str] = set()
        self.comp_depth = 0

    # ---- scope helpers -------------------------------------------------

    def _scope(self):
        return self.stack[-1]

    def _push(self, kind: str, name: str, *,
              is_method: bool = False, first_arg: str | None = None):
        if self.stack[-1]["kind"] == "func":
            self.qual_parts.append("<locals>")
        self.qual_parts.append(name)
        qualname = ".".join(self.qual_parts)
        if kind == "func":
            if is_method:
                self_name, self_owner = first_arg, self._enclosing_class()
            else:
                self_name = self.stack[-1]["self_name"]
                self_owner = self.stack[-1]["self_owner"]
        else:
            self_name = self_owner = None
        self.stack.append({"kind": kind, "name": name, "qualname": qualname,
                           "self_name": self_name, "self_owner": self_owner})
        return qualname

    def _pop(self):
        self.stack.pop()
        self.qual_parts.pop()
        if self.qual_parts and self.qual_parts[-1] == "<locals>":
            self.qual_parts.pop()

    def _enclosing_class(self) -> str | None:
        for scope in reversed(self.stack):
            if scope["kind"] == "class":
                return scope["qualname"]
        return None

    def _self(self) -> tuple[str | None, str | None]:
        """(first-arg name, owner class qualname) of the enclosing method."""
        return self._scope()["self_name"], self._scope()["self_owner"]

    def _class_info(self, qualname: str) -> ClassInfo:
        return self.classes[qualname]

    # ---- attribute recording -------------------------------------------

    def _record_write(self, qualname: str, attr: str, node, class_level: bool):
        info = self._class_info(qualname)
        mangled = _mangle(info.qualname.rsplit(".", 1)[-1], attr)
        info.written.setdefault(
            mangled, AttrSite(self.filename, node.lineno, attr, class_level))

    def _record_read(self, qualname: str, attr: str):
        info = self._class_info(qualname)
        self.statically_read_add(info, attr)

    @staticmethod
    def statically_read_add(info: ClassInfo, attr: str):
        mangled = _mangle(info.qualname.rsplit(".", 1)[-1], attr)
        info.statically_read.add(mangled)

    def _is_self_name(self, node, self_name: str | None) -> bool:
        return (self_name is not None
                and isinstance(node, ast.Name) and node.id == self_name)

    def _const_str(self, node) -> str | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        return None

    # ---- visitors -------------------------------------------------------

    def visit_ClassDef(self, node: ast.ClassDef):
        for expr in node.decorator_list + node.bases:
            self.visit(expr)
        for kw in node.keywords:
            self.visit(kw)
        qualname = self._push("class", node.name)
        info = ClassInfo(
            module=self.module, qualname=qualname,
            file=self.filename, line=node.lineno)
        info.is_dataclass = "dataclass" in self._decorator_names(node)
        self.classes[qualname] = info
        for stmt in node.body:
            self.visit(stmt)
        self._pop()

    def _decorator_names(self, node) -> set[str]:
        names = set()
        for dec in getattr(node, "decorator_list", []):
            target = dec.func if isinstance(dec, ast.Call) else dec
            if isinstance(target, ast.Name):
                names.add(target.id)
            elif isinstance(target, ast.Attribute):
                names.add(target.attr)
        return names

    def visit_FunctionDef(self, node):
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node):
        self._visit_function(node)

    def visit_Lambda(self, node: ast.Lambda):
        self._push("func", "<lambda>")
        self.visit(node.body)
        self._pop()

    def _visit_function(self, node):
        decs = self._decorator_names(node)
        is_method = self.stack[-1]["kind"] == "class" and "staticmethod" not in decs
        first_arg = None
        if is_method:
            pos = list(node.args.posonlyargs) + list(node.args.args)
            if pos:
                first_arg = pos[0].arg
        in_class = self.stack[-1]["kind"] == "class"
        self._push("func", node.name, is_method=is_method, first_arg=first_arg)
        self.stack[-1]["is_classmethod"] = "classmethod" in decs
        if in_class:
            owner = self._enclosing_class()
            if owner is not None:
                # also staticmethods: the qualname still identifies the class
                self._class_info(owner).method_qualnames.add(
                    self.stack[-1]["qualname"])
        for default in node.args.defaults + node.args.kw_defaults:
            if default is not None:
                self.visit(default)
        for stmt in node.body:
            self.visit(stmt)
        self._pop()

    def visit_ListComp(self, node):
        self.comp_depth += 1
        self.generic_visit(node)
        self.comp_depth -= 1

    visit_SetComp = visit_ListComp
    visit_DictComp = visit_ListComp
    visit_GeneratorExp = visit_ListComp

    def visit_Attribute(self, node: ast.Attribute):
        self_name, owner = self._self()
        if isinstance(node.ctx, ast.Load):
            self.global_reads.add(node.attr)
            if owner is not None:
                self._record_attr_load(owner, self_name, node)
        elif (isinstance(node.ctx, (ast.Store, ast.Del))
              and owner is not None
              and self._is_self_name(node.value, self_name)):
            if isinstance(node.ctx, ast.Store):
                class_level = bool(self._scope().get("is_classmethod"))
                self._record_write(owner, node.attr, node, class_level)
            else:  # del self.x counts as a read of the name
                self._record_read(owner, node.attr)
        self.generic_visit(node)

    def _record_attr_load(self, owner, self_name, node: ast.Attribute):
        base = node.value
        if self._is_self_name(base, self_name):
            if node.attr == "__dict__":
                self._class_info(owner).bulk_introspected = True
            else:
                self._record_read(owner, node.attr)
        elif (isinstance(base, ast.Call)
              and isinstance(base.func, ast.Name)
              and base.func.id in ("super", "type")):
            # super().x / type(self).x
            self._record_read(owner, node.attr)
        elif (isinstance(base, ast.Attribute)
              and base.attr == "__class__"
              and self._is_self_name(base.value, self_name)):
            self._record_read(owner, node.attr)

    def visit_Name(self, node: ast.Name):
        # class-body assignment:  class C: x = 1   ->  class attribute
        if (self._scope()["kind"] == "class" and self.comp_depth == 0):
            qualname = self._scope()["qualname"]
            if isinstance(node.ctx, ast.Store):
                if not (node.id.startswith("__") and node.id.endswith("__")):
                    self._record_write(qualname, node.id, node,
                                       class_level=True)
            elif isinstance(node.ctx, (ast.Load, ast.Del)):
                self._record_read(qualname, node.id)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign):
        # "self.x += 1" both reads and writes x
        self_name, owner = self._self()
        if (owner is not None and isinstance(node.target, ast.Attribute)
                and self._is_self_name(node.target.value, self_name)):
            self._record_read(owner, node.target.attr)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign):
        # class-body "x: int" -- a real write for dataclasses/annotated
        # assignments with a value, a bare annotation otherwise
        if (self._scope()["kind"] == "class"
                and self.comp_depth == 0
                and isinstance(node.target, ast.Name)):
            info = self._class_info(self._scope()["qualname"])
            if node.value is not None or info.is_dataclass:
                self._record_write(info.qualname,
                                   node.target.id, node, class_level=True)
        if node.value is None:
            # bare "self.x: int" assigns nothing -- not a write
            self.visit(node.annotation)
            return
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        self_name, owner = self._self()
        if owner is not None and node.args:
            func = node.func
            func_name = (func.id if isinstance(func, ast.Name)
                         else func.attr if isinstance(func, ast.Attribute)
                         else None)
            arg0 = node.args[0]
            if self._is_self_name(arg0, self_name):
                info = self._class_info(owner)
                if func_name in ("getattr", "hasattr") and len(node.args) >= 2:
                    const = self._const_str(node.args[1])
                    if const is not None:
                        self.statically_read_add(info, const)
                elif func_name == "setattr" and len(node.args) >= 3:
                    const = self._const_str(node.args[1])
                    if const is not None:
                        self._record_write(owner, const, node, class_level=False)
                elif func_name in _BULK_INTROSPECTION or func_name in ("copy", "deepcopy", "dumps"):
                    info.bulk_introspected = True
        self.generic_visit(node)


def _module_name(path: str, root: str) -> str:
    rel = os.path.relpath(path, root)
    parts = rel.split(os.sep)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = os.path.splitext(parts[-1])[0]
    return ".".join(p for p in parts if p and p != ".")


def iter_python_files(root: str):
    if os.path.isfile(root):
        yield os.path.abspath(root)
        return
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS
                       and not d.startswith(".")]
        for name in filenames:
            if name.endswith(".py"):
                yield os.path.join(dirpath, name)


def analyze_file(path: str, module: str, analysis: Analysis):
    with open(path, "r", encoding="utf-8") as f:
        source = f.read()
    tree = ast.parse(source, filename=path)
    visitor = _Visitor(module, path)
    visitor.visit(tree)
    analysis.classes.setdefault(module, {}).update(visitor.classes)
    analysis.global_attr_reads |= visitor.global_reads


def analyze(root: str, skip: frozenset[str] = frozenset()) -> Analysis:
    """Analyze every .py file under *root*; returns class-level findings."""
    root = os.path.abspath(root)
    # never instrument the tool's own modules
    own_pkg = os.path.dirname(os.path.abspath(__file__)) + os.sep
    analysis = Analysis(root=root)
    for path in iter_python_files(root):
        if path in skip or path.startswith(own_pkg):
            continue
        try:
            analyze_file(path, _module_name(path, root), analysis)
        except (SyntaxError, OSError, UnicodeDecodeError):
            continue
    # second pass: bulk introspection & class-level attribute reads
    for module_classes in analysis.classes.values():
        for info in module_classes.values():
            if info.bulk_introspected:
                info.statically_read |= set(info.written)
            for mangled, site in info.written.items():
                if site.class_level and mangled in analysis.global_attr_reads:
                    # C.x style reads can't be tracked at runtime -> be lenient
                    info.statically_read.add(mangled)
    return analysis
