"""calc / memory / registry tests."""

import asyncio

from backend.tools import memory, pyexec
from backend.tools.registry import TOOL_SPECS, dispatch, preview
from tests.base import BaseTestCase


class CalcTests(BaseTestCase):
    def test_basic_arithmetic(self):
        self.assertEqual(pyexec.calc("2+2*2"), "6")
        self.assertEqual(pyexec.calc("(1200*1.24)/3"), "496.0")
        self.assertEqual(pyexec.calc("10/4"), "2.5")

    def test_functions_and_consts(self):
        self.assertEqual(pyexec.calc("sqrt(144)"), "12.0")
        self.assertEqual(pyexec.calc("pi*2"), str(2 * 3.141592653589793))
        self.assertEqual(pyexec.calc("max(3,7,1)"), "7")
        self.assertEqual(pyexec.calc("round(3.14159, 2)"), "3.14")
        self.assertEqual(pyexec.calc("factorial(5)"), "120")

    def test_rejects_dangerous_input(self):
        for expr in (
            "__import__('os').system('ls')",
            "().__class__",
            "os",
            "lambda: 1",
            "[x for x in range(3)]",
            "'a'+'b'",
            "",
        ):
            res = pyexec.calc(expr)
            self.assertTrue(res.startswith("error"), f"{expr!r} should fail, got {res!r}")

    def test_division_by_zero(self):
        self.assertTrue(pyexec.calc("1/0").startswith("error"))

    def test_huge_pow_guard(self):
        res = pyexec.calc("10**99999999")
        self.assertTrue(res.startswith("error"))


class CalcExecTests(BaseTestCase):
    def test_python_runs_and_prints(self):
        out = pyexec.run_python("print(40+2)")
        self.assertIn("42", out)
        self.assertIn("stdout", out)

    def test_python_timeout(self):
        out = pyexec.run_python("import time\ntime.sleep(30)")
        self.assertTrue(out.startswith("error:"))

    def test_python_no_stdin_hang(self):
        out = pyexec.run_python("import sys; sys.stdin.read()")
        out = pyexec.run_python("print('echo ok')")
        self.assertIn("echo ok", out)


class MemoryTests(BaseTestCase):
    def test_write_search_snapshot(self):
        res = memory.upsert("user likes dark mode")
        self.assertTrue(res.startswith("note saved"))
        res = memory.upsert("project: selfhost chat")
        self.assertTrue(res.startswith("note saved"))
        found = memory.search("dark")
        self.assertIn("dark mode", found)
        self.assertNotIn("selfhost", found)
        snap = memory.snapshot(500)
        self.assertIn("dark mode", snap)

    def test_empty_ignored(self):
        self.assertEqual(memory.upsert("   "), "empty note ignored")


class RegistryTests(BaseTestCase):
    def test_specs_wellformed(self):
        names = {s["function"]["name"] for s in TOOL_SPECS}
        self.assertEqual(names, {"web_search", "fetch_page", "calc", "python", "memory_write", "memory_list"})
        for spec in TOOL_SPECS:
            self.assertIn("description", spec["function"])
            self.assertEqual(spec["type"], "function")

    def test_dispatch_unknown(self):
        res, ok, ms = asyncio.run(dispatch("no_such_tool", {}))
        self.assertFalse(ok)
        self.assertIn("unknown tool", res)

    def test_dispatch_calc_end_to_end(self):
        res, ok, ms = asyncio.run(dispatch("calc", {"expr": "6*7"}))
        self.assertTrue(ok)
        self.assertEqual(res, "42")
        self.assertGreaterEqual(ms, 0)

    def test_dispatch_memory_tools_end_to_end(self):
        # every spec must survive dispatch(), not just be callable directly
        res, ok, ms = asyncio.run(dispatch("memory_write", {"content": "user prefers tabs"}))
        self.assertTrue(ok)
        self.assertTrue(res.startswith("note saved"), res)
        res, ok, ms = asyncio.run(dispatch("memory_list", {"query": "tabs"}))
        self.assertTrue(ok)
        self.assertIn("tabs", res)

    def test_all_impls_are_awaitable(self):
        # dispatch() awaits every impl, so a bare sync function breaks it
        from inspect import iscoroutinefunction

        from backend.tools.registry import tool_impls

        for name, fn in tool_impls().items():
            self.assertTrue(iscoroutinefunction(fn), f"{name} would break await in dispatch()")

    def test_preview(self):
        self.assertEqual(preview("x" * 50), "x" * 50)
        self.assertEqual(len(preview("y" * 1000)), 501)


if __name__ == "__main__":
    unittest.main()