"""calc (safe AST evaluator) + python (subprocess with rlimits) tools."""

import ast
import math
import operator
import os
import resource
import shutil
import subprocess
import tempfile

from backend.config import settings

# --- calc: allowed AST node types and math universe -------------------------

_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARYOPS = {ast.USub: operator.neg, ast.UAdd: operator.pos}
_CONSTS = {"pi": math.pi, "e": math.e, "tau": math.tau, "inf": math.inf}
_FUNCS = {
    "sqrt": math.sqrt, "log": math.log, "log2": math.log2, "log10": math.log10,
    "exp": math.exp, "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "asin": math.asin, "acos": math.acos, "atan": math.atan, "atan2": math.atan2,
    "floor": math.floor, "ceil": math.ceil, "fabs": math.fabs, "factorial": math.factorial,
    "gcd": math.gcd, "radians": math.radians, "degrees": math.degrees, "round": round,
    "min": min, "max": max, "abs": abs, "sum": sum, "pow": pow,
}


def calc(expr: str) -> str:
    src = expr.strip()
    if not src:
        return "error: empty expression"

    def visit(node: ast.AST) -> object:
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
            left, right = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Pow) and (
                (isinstance(left, (int, float)) and abs(left) > 10_000) or (isinstance(right, (int, float)) and right > 1000)
            ):
                raise ValueError("exponent too large")
            return _BINOPS[type(node.op)](left, right)  # type: ignore[index]
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARYOPS:
            return _UNARYOPS[type(node.op)](visit(node.operand))  # type: ignore[index]
        if isinstance(node, ast.Name) and node.id in _CONSTS:
            return _CONSTS[node.id]
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS:
            return _FUNCS[node.func.id](*[visit(a) for a in node.args])
        raise ValueError(f"unsupported expression: {type(node).__name__}")

    try:
        tree = ast.parse(src, mode="eval")
        result = visit(tree)
        if isinstance(result, (int, float)):
            if isinstance(result, float) and (math.isnan(result) or math.isinf(result) or abs(result) > 1e15):
                return f"{result!r}"
            return str(result)
        return repr(result)
    except (ValueError, TypeError, ZeroDivisionError, OverflowError, SyntaxError) as exc:
        return f"error: {exc}"


# --- python: subprocess with hard limits -----------------------------------


def _set_limits() -> None:
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_CPU, (5, 7))
    resource.setrlimit(resource.RLIMIT_NPROC, (8, 8))
    resource.setrlimit(resource.RLIMIT_FSIZE, (5 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))


def run_python(code: str) -> str:
    if not code.strip():
        return "error: empty code"
    argv = [shutil.which("python3") or "python3", "-I", "-c", code]
    if not settings.pyexec_network and shutil.which("unshare"):
        argv = ["unshare", "-r", "-n", *argv]
    cwd = tempfile.mkdtemp(prefix="shc_py_")
    try:
        proc = subprocess.run(
            argv,
            cwd=cwd,
            capture_output=True,
            timeout=settings.pyexec_timeout,
            preexec_fn=_set_limits,
        )
        stdout = proc.stdout.decode("utf-8", "replace")[:4000]
        stderr = proc.stderr.decode("utf-8", "replace")[-3000:]
        parts = []
        if stdout:
            parts.append(f"stdout:\n{stdout}")
        if proc.returncode != 0:
            parts.append(f"exit code: {proc.returncode}")
        if stderr:
            parts.append(f"stderr:\n{stderr}")
        return "\n".join(parts) if parts else "(no output)"
    except subprocess.TimeoutExpired:
        return f"error: timed out after {settings.pyexec_timeout}s"
    except Exception as exc:
        return f"error: {exc.__class__.__name__}: {exc}"
    finally:
        try:
            for f in os.listdir(cwd):
                os.unlink(os.path.join(cwd, f))
            os.rmdir(cwd)
        except OSError:
            pass