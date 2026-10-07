"""unused_attributes -- find class attributes that are written but never read.

Hybrid analysis: a static (AST) pass enumerates attribute writes and
provable reads per class; a runtime pass then instruments only the
remaining candidate classes and measures actual reads while the target
program runs.  Results therefore reflect what the exercised code paths
really did -- run it against your test suite for best coverage.
"""
from __future__ import annotations

import argparse
import os
import runpy
import sys

from ._runtime import Tracker
from ._static import _module_name, analyze

__version__ = "0.3.0"

__all__ = ["Tracker", "analyze", "main"]


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="unused_attributes",
        description="Find class attributes that are assigned but never read "
                    "at runtime.")
    parser.add_argument("script", help="Python script to run under tracing")
    parser.add_argument("script_args", nargs=argparse.REMAINDER,
                        help="arguments passed to the script")
    parser.add_argument("--root", default=None,
                        help="source tree to analyze (default: script dir)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    script = os.path.abspath(args.script)
    if not os.path.isfile(script):
        parser.error(f"no such file: {args.script}")
    script_dir = os.path.dirname(script)
    root = os.path.abspath(args.root) if args.root else script_dir

    analysis = analyze(root)
    script_module = _module_name(script, root)
    tracker = Tracker(analysis, script_module=script_module,
                      verbose=args.verbose)
    tracker.start()

    sys.path.insert(0, script_dir)
    sys.argv = [script] + args.script_args
    runpy.run_path(script, run_name="__main__")


if __name__ == "__main__":
    main()
