import os
import subprocess
import sys
import textwrap

PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_tool(script_dir, script="prog.py", *extra):
    env = dict(os.environ)
    env["PYTHONPATH"] = PKG + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [sys.executable, "-m", "unused_attributes", script, *extra],
        cwd=script_dir, env=env, capture_output=True, text=True,
        check=False)
    return proc


def write(tmp_path, name, source):
    p = tmp_path / name
    p.write_text(textwrap.dedent(source))
    return p


def warnings_of(proc):
    return [l for l in proc.stdout.splitlines() if "W001" in l]


def test_basic(tmp_path):
    write(tmp_path, "prog.py", """\
        class C:
            def __init__(self):
                self.used = 0
                self.dead = 1

        c = C()
        print(c.used)
        """)
    out = warnings_of(run_tool(tmp_path))
    assert len(out) == 1
    assert "attribute 'dead' was never read" in out[0]
    assert "used" not in out[0]


def test_external_write_and_getattr(tmp_path):
    write(tmp_path, "prog.py", """\
        class C:
            def __init__(self):
                self.a = 0

        c = C()
        c.extra = 5                # dynamic attr, never read
        print(getattr(c, "a"))     # dynamic read of a
        """)
    out = warnings_of(run_tool(tmp_path))
    assert len(out) == 1
    assert "'extra'" in out[0]


def test_subclass_aggregation(tmp_path):
    write(tmp_path, "prog.py", """\
        class A:
            def __init__(self):
                self.x = 1
                self.y = 2

        class Sub(A):
            def __init__(self):
                super().__init__()
                self.extra = 9

        a = A()
        print(a.x)                 # read on A instance -> used everywhere
        s = Sub()
        """)
    out = warnings_of(run_tool(tmp_path))
    names = [l for l in out]
    assert any("'y'" in l and "class A" in l for l in names)
    assert any("'extra'" in l and "class Sub" in l for l in names)
    # x was read on the A instance: not reported under Sub either
    assert not any("'x'" in l for l in names)
    # each attribute reported once
    assert len(names) == 2


def test_static_and_classmethod(tmp_path):
    write(tmp_path, "prog.py", """\
        class Sm:
            def __init__(self):
                self.s1 = 1
            @staticmethod
            def make():
                return 42

        class Cm:
            def __init__(self):
                self.c1 = 1
            @classmethod
            def build(cls):
                return cls

        Sm.make()
        Cm.build()
        """)
    out = warnings_of(run_tool(tmp_path))
    assert any("'s1'" in l for l in out)
    assert any("'c1'" in l for l in out)


def test_imported_module(tmp_path):
    write(tmp_path, "helper.py", """\
        class H:
            def __init__(self):
                self.live = 1
                self.dead = 2
            def use(self):
                return self.live
        """)
    write(tmp_path, "prog.py", """\
        import helper
        h = helper.H()
        h.use()
        """)
    out = warnings_of(run_tool(tmp_path))
    assert len(out) == 1
    assert "'dead'" in out[0] and "class H" in out[0]


def test_dict_introspection_suppresses(tmp_path):
    write(tmp_path, "prog.py", """\
        class C:
            def __init__(self):
                self.a = 0
                self.b = 1
            def dump(self):
                return dict(self.__dict__)

        c = C()
        c.dump()
        """)
    out = warnings_of(run_tool(tmp_path))
    assert out == []


def test_main_guard_and_script_args(tmp_path):
    write(tmp_path, "prog.py", """\
        import sys
        class C:
            def __init__(self):
                self.dead = 1
        if __name__ == "__main__":
            assert sys.argv[1] == "hello"
            C()
        """)
    proc = run_tool(tmp_path, "prog.py", "hello")
    out = warnings_of(proc)
    assert len(out) == 1 and "'dead'" in out[0]


def test_never_instantiated_not_reported(tmp_path):
    write(tmp_path, "prog.py", """\
        class N:
            def __init__(self):
                self.n1 = 1
        print("done")
        """)
    proc = run_tool(tmp_path, "prog.py", "-v")
    assert warnings_of(proc) == []
    assert "never exercised" in proc.stderr


def test_local_class(tmp_path):
    write(tmp_path, "prog.py", """\
        def make():
            class L:
                def __init__(self):
                    self.dead = 1
                    self.live = 2
                def use(self):
                    return self.live
            return L()
        o = make()
        o.use()
        """)
    out = warnings_of(run_tool(tmp_path))
    assert len(out) == 1
    assert "'dead'" in out[0] and "class make.<locals>.L" in out[0]


def run_pytest(script_dir, *extra):
    env = dict(os.environ)
    env["PYTHONPATH"] = PKG + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q",
         "-p", "unused_attributes.pytest_plugin",
         "-p", "no:cacheprovider", *extra],
        cwd=script_dir, env=env, capture_output=True, text=True,
        check=False)


def test_pytest_plugin(tmp_path):
    write(tmp_path, "app.py", """\
        class A:
            def __init__(self):
                self.live = 1
                self.dead = 2
            def use(self):
                return self.live
        """)
    write(tmp_path, "test_app.py", """\
        import app
        def test_it():
            a = app.A()
            assert a.use() == 1
        """)
    proc = run_pytest(tmp_path, "--unused-attrs")
    assert proc.returncode == 0, proc.stderr
    assert "unused attributes" in proc.stdout
    assert "attribute 'dead' was never read" in proc.stdout
    assert "'live'" not in proc.stdout


def test_pytest_plugin_fail_flag(tmp_path):
    write(tmp_path, "app.py", """\
        class A:
            def __init__(self):
                self.dead = 2
        """)
    write(tmp_path, "test_app.py", """\
        import app
        def test_it():
            app.A()
        """)
    proc = run_pytest(tmp_path, "--unused-attrs", "--unused-attrs-fail")
    assert proc.returncode != 0
    assert "attribute 'dead' was never read" in proc.stdout


def test_pytest_plugin_off_by_default(tmp_path):
    write(tmp_path, "app.py", """\
        class A:
            def __init__(self):
                self.dead = 2
        """)
    write(tmp_path, "test_app.py", "def test_it(): pass\n")
    proc = run_pytest(tmp_path)
    assert proc.returncode == 0
    assert "unused attributes" not in proc.stdout


def test_slots_and_dataclass(tmp_path):
    write(tmp_path, "prog.py", """\
        from dataclasses import dataclass, asdict

        class S:
            __slots__ = ("a", "b")
            def __init__(self):
                self.a = 1
                self.b = 2
            def use(self):
                return self.b

        @dataclass
        class D:
            x: int = 0
            y: int = 0

        s = S()
        s.use()
        d = D(1, 2)
        asdict(d)               # bulk read -> both fields used
        """)
    out = warnings_of(run_tool(tmp_path))
    assert len(out) == 1
    assert "'a'" in out[0] and "class S" in out[0]
