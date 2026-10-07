"""pytest plugin: track class attribute reads across the test suite.

    pytest --unused-attrs [--unused-attrs-root DIR] [--unused-attrs-fail]

Findings are coverage-bound: attributes are only verified on the classes
your tests actually exercise.
"""
from __future__ import annotations

import pytest

from ._runtime import Tracker
from ._static import analyze


def pytest_addoption(parser):
    group = parser.getgroup("unused_attributes")
    group.addoption("--unused-attrs", action="store_true",
                    help="report class attributes that are written but never "
                         "read during the test run")
    group.addoption("--unused-attrs-root", metavar="DIR", default=None,
                    help="source tree to analyze (default: pytest rootdir)")
    group.addoption("--unused-attrs-fail", action="store_true",
                    help="fail the test session if never-read attributes "
                         "are found")


def pytest_configure(config):
    if not config.getoption("--unused-attrs"):
        return
    root = config.getoption("--unused-attrs-root") or str(config.rootdir)
    verbose = config.getoption("verbose", 0) > 0
    tracker = Tracker(analyze(root), verbose=verbose)
    tracker.start(register_exit=False)
    config._unused_attrs_tracker = tracker


def pytest_sessionfinish(session, exitstatus):
    tracker = getattr(session.config, "_unused_attrs_tracker", None)
    if tracker is None:
        return
    result = tracker.finish()
    if result.lines and session.config.getoption("--unused-attrs-fail"):
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    tracker = getattr(config, "_unused_attrs_tracker", None)
    if tracker is None:
        return
    result = tracker.finish()
    terminalreporter.section("unused attributes")
    if result.lines:
        for line in result.lines:
            terminalreporter.line(line)
    else:
        terminalreporter.line("no never-read attributes found")
    if result.unexercised:
        terminalreporter.line(
            f"note: {len(result.unexercised)} candidate class(es) were never "
            f"exercised; their attributes were not checked")
        if config.getoption("verbose", 0) > 0:
            for name in result.unexercised:
                terminalreporter.line(f"  {name}")
