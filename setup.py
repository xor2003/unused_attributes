"""Optional Cython build for the hot-path module.

_installing_ unused_attributes never requires Cython: the package works
pure-Python.  When Cython is available at build time, unused_attributes/_hot.py
is compiled to an extension module (same file name -> automatically picked
over the .py at import time), speeding up the per-attribute-access wrappers.
"""
from setuptools import setup

ext_modules = []
try:
    from Cython.Build import cythonize
except ImportError:
    pass
else:
    ext_modules = cythonize(
        ["unused_attributes/_hot.py"],
        compiler_directives={"language_level": "3"},
    )

setup(ext_modules=ext_modules)
