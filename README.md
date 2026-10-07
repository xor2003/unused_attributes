# Unused attributes

Finds class attributes that are **assigned a value but never read** — dead
state you can usually delete.

Unlike static dead-code checkers (vulture, etc.) which can only *guess* at
attribute usage — and get fooled by `getattr`, `self.__dict__` access,
serialization, and same-named attributes on unrelated classes — this tool
works in two stages:

1. **Static pass (AST).** Scans the source tree and enumerates, per class,
   every `self.x = ...` / `cls.x = ...` / class-body attribute write, plus
   provable reads (`self.x` loads, `getattr(self, "x")`, `super().x`,
   `self.__dict__` / `vars(self)` bulk introspection, ...). Attributes
   already provably read are excluded up front.
2. **Runtime pass.** Runs your program under `sys.monitoring` and patches
   `__getattribute__` / `__setattr__` **only on the remaining candidate
   classes**, counting actual reads and writes. Monitoring disables itself
   once all candidates have been seen, and attributes are deduplicated by
   their definition site across the class hierarchy (a base-class attribute
   read through a subclass instance counts as used).

## Usage

    unused_attributes <script.py> [script args...]
    python -m unused_attributes <script.py> [script args...]

To get meaningful results the run should exercise the code — typically run
it against your test suite entry point or your app's main script.

Example:

    $ unused_attributes test.py
    /path/test.py:3: W001: in class C attribute 'd' was never read
    /path/test.py:7: W001: in class C attribute 'b' was never read
    /path/test.py:13: W001: in class C attribute 'e' was never read

Options:

* `--root DIR` — analyze a different source tree (default: the script's
  directory, scanned recursively)
* `-v` / `--verbose` — also list candidate classes that were never
  exercised

## Pytest plugin

The package registers a pytest plugin (`pytest11` entry point). Once
installed, run your test suite with:

    pytest --unused-attrs

Findings appear in an `unused attributes` section of the terminal summary.
Options:

* `--unused-attrs-root DIR` — source tree to analyze (default: pytest's
  rootdir)
* `--unused-attrs-fail` — fail the test session when never-read attributes
  are found
* `-v` — list candidate classes that were never exercised

Without `--unused-attrs` the plugin is completely inert. If the plugin is
not installed, load it explicitly with
`pytest -p unused_attributes.pytest_plugin --unused-attrs` (with the
package on `PYTHONPATH` or installed).

On a real 2834-test project (masm2c) the plugin added ~5% runtime and
reported 56 never-read attributes.

## Requirements & performance

* Python >= 3.12 (uses `sys.monitoring`; no `sys.settrace`)
* Optional: build with Cython to compile the per-access wrappers
  (`pip install .[cython]` or just have `cython` available at build time);
  pure-Python fallback works without it.

Runtime overhead is small: only candidate classes are instrumented, the
call monitor self-disables once every candidate has been seen, and the
hot path is a single dict probe per attribute access (~15% on an
attribute-heavy microbenchmark).

## Development

    pip install -e .[dev]        # pytest, ruff, mypy, lizard

Lint (all of these run in GitHub CI):

    ruff check .                 # style + correctness
    mypy                         # type checking (config in pyproject.toml)
    lizard unused_attributes/ tests/ test.py -x"*_hot.c"   # complexity
    npx basta .                  # dead code (JS/TS/Python/Rust engine)

## Caveats

* **Coverage matters.** "Never read during this run" ≠ "never read".
  Attributes in unexercised code paths may be falsely reported; classes
  that are never instantiated are listed as notes instead.
* Reads that bypass `__getattribute__` are invisible: `obj.__dict__["x"]`,
  `vars(obj)`, `pickle`/`copyreg` `__reduce__` internals. The static pass
  marks obvious bulk-introspection patterns to reduce false positives.
* Instances created without ever calling a Python method (e.g.
  unpickled data bags that are only poked at from outside) may be missed.
