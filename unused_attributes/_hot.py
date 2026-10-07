"""Hot-path wrappers installed on candidate classes.

Kept in a separate module so it can optionally be compiled with Cython
(pure-Python mode) -- setup.py cythonizes this file when Cython is
available at build time.  It must stay free of dynamic tricks so the
compiled version behaves identically.
"""
import sys


def _unwrap(fn):
    """Return the real original behind our own wrappers (stacked patching)."""
    seen = set()
    while getattr(fn, "__ua_orig__", None) is not None and id(fn) not in seen:
        seen.add(id(fn))
        fn = fn.__ua_orig__
    return fn


def install(cls, counts, sites, owner, root=""):
    """Patch cls.__getattribute__ / cls.__setattr__ to track attribute use.

    counts: dict attr_name -> read count (pre-seeded by the caller)
    sites:  dict attr_name -> (file, line, display_name, owner_qualname)
    owner:  qualname used for attributes first seen written on cls
    root:   path prefix; dynamically-discovered write sites outside it are
            ignored (base-class internals from libraries are not findings)
    Returns True on success.
    """
    try:
        orig_get = _unwrap(cls.__getattribute__)
        orig_set = _unwrap(cls.__setattr__)
    except AttributeError:
        return False

    def __getattribute__(self, name, _counts=counts, _orig=orig_get):
        if name in _counts:
            _counts[name] += 1
        return _orig(self, name)

    def __setattr__(self, name, value,
                    _counts=counts, _sites=sites, _orig=orig_set,
                    _owner=owner, _me=__file__, _root=root):
        if name not in _counts:
            # compiled versions of this module leave no Python frame, so
            # walk to the first frame outside this file
            frame = sys._getframe(0)
            while frame.f_code.co_filename == _me:
                frame = frame.f_back
            fname = frame.f_code.co_filename
            if not _root or fname.startswith(_root):
                _counts[name] = 0
                _sites[name] = (fname, frame.f_lineno, name, _owner)
        return _orig(self, name, value)

    __getattribute__.__ua_orig__ = orig_get
    __setattr__.__ua_orig__ = orig_set
    try:
        cls.__getattribute__ = __getattribute__
        cls.__setattr__ = __setattr__
    except (AttributeError, TypeError):
        return False
    return True
