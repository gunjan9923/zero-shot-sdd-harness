"""Restricted local execution of LLM-generated pandas code.

LLM-generated code is treated as untrusted. The sandbox runs it in a minimal
namespace (only ``pd``, ``np``, the bound DataFrame(s), and a curated set of
safe builtins), behind an AST allow-list that rejects disallowed imports,
dangerous builtins, and dunder attribute access, with a wall-clock timeout.

Mechanism choice — AST allow-list (not RestrictedPython): RestrictedPython
over-restricts the everyday pandas idioms this agent depends on (it rewrites
subscripting such as ``df['col']`` into ``_getitem_`` guards and blocks plain
attribute access like ``series.sum()`` unless every guard is supplied). The
denylist below (os/sys/subprocess/open/eval/exec/__import__ + dunders +
non-allow-listed imports) is the security boundary and is verified by tests.

Contract::

    run_pandas(code, dataframes, *, timeout_s=None) -> {
        "result": <value of `result` var or None>,
        "stdout": str,
        "error":  str | None,
    }

The function NEVER raises: every failure (rejected code, runtime exception,
timeout) is returned with ``error`` set and ``result`` None.
"""

from __future__ import annotations

import ast
import contextlib
import io
import math
import os
import statistics
import threading
import traceback
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

if TYPE_CHECKING:  # pragma: no cover - typing only
    pass

# --- Security boundary -------------------------------------------------------

# Modules generated code is permitted to import.
ALLOWED_IMPORTS: frozenset[str] = frozenset(
    {"pandas", "numpy", "math", "datetime", "statistics"}
)

# Attribute names that write to the filesystem / network and must be blocked.
# pandas' ``DataFrame.to_csv`` (and friends) open files through pandas' own IO
# layer, NOT the bound ``__builtins__.open`` — so denying ``open`` alone does
# not stop a write. We reject these method names statically at the AST level.
DENIED_ATTRS: frozenset[str] = frozenset(
    {
        "to_csv",
        "to_excel",
        "to_parquet",
        "to_pickle",
        "to_json",
        "to_hdf",
        "to_feather",
        "to_sql",
        "to_html",
        "to_xml",
        "to_stata",
        "to_orc",
        "to_latex",
        "to_clipboard",
        "to_markdown",
        "to_string",  # writes when given a buf/path
        "to_gbq",
        "read_pickle",  # pickle deserialization is unsafe
        "system",
        "popen",
        "remove",
        "unlink",
        "rmdir",
        "makedirs",
        "mkdir",
    }
)

# Names that must never be referenced, bound, or reachable from generated code.
DENIED_NAMES: frozenset[str] = frozenset(
    {
        "open",
        "eval",
        "exec",
        "compile",
        "__import__",
        "os",
        "sys",
        "subprocess",
        "socket",
        "shutil",
        "pathlib",
        "globals",
        "locals",
        "vars",
        "getattr",
        "setattr",
        "delattr",
        "input",
        "breakpoint",
        "memoryview",
        "classmethod",
        "staticmethod",
    }
)

# Curated safe builtins exposed inside the sandbox.
_SAFE_BUILTIN_NAMES: tuple[str, ...] = (
    "len",
    "sum",
    "min",
    "max",
    "abs",
    "round",
    "sorted",
    "range",
    "enumerate",
    "zip",
    "list",
    "dict",
    "set",
    "tuple",
    "str",
    "int",
    "float",
    "bool",
    "print",
    "all",
    "any",
    "map",
    "filter",
    "reversed",
    "divmod",
    "pow",
    "isinstance",
    "Exception",
    "ValueError",
    "KeyError",
    "TypeError",
    "ZeroDivisionError",
)

# Modules made importable inside the sandbox, keyed by import name.
_ALLOWED_MODULES: dict[str, Any] = {
    "pandas": pd,
    "numpy": np,
    "math": math,
    "statistics": statistics,
    # `datetime` is a module; expose the module object so `datetime.datetime`,
    # `datetime.date`, `datetime.timedelta` all work.
    "datetime": __import__("datetime"),
}

_DEFAULT_TIMEOUT_S = 25


def _safe_builtins() -> dict[str, Any]:
    import builtins as _b

    return {name: getattr(_b, name) for name in _SAFE_BUILTIN_NAMES}


def _sandbox_import(
    name: str,
    globals_=None,
    locals_=None,
    fromlist=(),
    level: int = 0,
):
    """Restricted ``__import__`` honouring the allow-list only."""
    root = name.split(".")[0]
    if level != 0 or root not in ALLOWED_IMPORTS:
        raise ImportError(f"import of '{name}' is not allowed in the sandbox")
    return __import__(name, globals_, locals_, fromlist, level)


class SandboxError(Exception):
    """Raised by the AST validator when code violates the security policy."""


def _validate_ast(tree: ast.AST) -> None:
    """Reject disallowed imports, denied names, and dunder attribute access.

    Raises ``SandboxError`` (no execution side effect) on any violation.
    """
    for node in ast.walk(tree):
        # --- imports: only the allow-list, no relative/star imports ---------
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root not in ALLOWED_IMPORTS:
                    raise SandboxError(
                        f"import of '{alias.name}' is not allowed"
                    )
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                raise SandboxError("relative imports are not allowed")
            root = (node.module or "").split(".")[0]
            if root not in ALLOWED_IMPORTS:
                raise SandboxError(
                    f"import from '{node.module}' is not allowed"
                )
        # --- denied bare names ----------------------------------------------
        elif isinstance(node, ast.Name):
            if node.id in DENIED_NAMES:
                raise SandboxError(f"use of name '{node.id}' is not allowed")
            if node.id.startswith("__") and node.id.endswith("__"):
                raise SandboxError(
                    f"use of dunder name '{node.id}' is not allowed"
                )
        # --- block dunder attribute access (e.g. obj.__class__, __globals__) -
        elif isinstance(node, ast.Attribute):
            attr = node.attr
            if attr.startswith("__") and attr.endswith("__"):
                raise SandboxError(
                    f"access to dunder attribute '{attr}' is not allowed"
                )
            if attr in DENIED_ATTRS:
                raise SandboxError(
                    f"access to attribute '{attr}' is not allowed "
                    "(filesystem/network write blocked)"
                )


def _build_namespace(dataframes: dict[str, pd.DataFrame]) -> dict[str, Any]:
    """Assemble the restricted globals for exec.

    Each DataFrame is passed as a COPY so the source data stays read-only.
    """
    ns: dict[str, Any] = {
        "__builtins__": {**_safe_builtins(), "__import__": _sandbox_import},
        "pd": pd,
        "np": np,
        # Convenience handles for the allowed stdlib modules without an import.
        "math": math,
        "statistics": statistics,
        "datetime": datetime,
        "timedelta": timedelta,
    }
    for key, frame in dataframes.items():
        if not isinstance(frame, pd.DataFrame):
            raise TypeError(f"value for '{key}' is not a pandas DataFrame")
        ns[key] = frame.copy(deep=True)
    return ns


def _resolve_timeout(timeout_s: int | None) -> int:
    if timeout_s is not None:
        return int(timeout_s)
    raw = os.environ.get("AGENT_EXEC_TIMEOUT_S", "").strip()
    if raw:
        try:
            return int(raw)
        except ValueError:
            return _DEFAULT_TIMEOUT_S
    return _DEFAULT_TIMEOUT_S


def run_pandas(
    code: str,
    dataframes: dict[str, pd.DataFrame],
    *,
    timeout_s: int | None = None,
) -> dict[str, Any]:
    """Run an LLM-generated pandas snippet in the restricted sandbox.

    Args:
        code: a pandas snippet that assigns its answer to a variable ``result``.
        dataframes: mapping of namespace name -> DataFrame (Phase 1 binds
            ``{"df": ...}``; multi-file later binds ``dfs``/multiple names).
        timeout_s: wall-clock limit; defaults to ``AGENT_EXEC_TIMEOUT_S`` or 25.

    Returns:
        ``{"result": <value or None>, "stdout": str, "error": str | None}``.
        Never raises — all failures are reported via ``error``.
    """
    timeout = _resolve_timeout(timeout_s)

    # --- 1. parse + static validation (rejects with NO execution) ----------
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as exc:
        return {
            "result": None,
            "stdout": "",
            "error": f"SyntaxError: {exc}",
        }

    try:
        _validate_ast(tree)
    except SandboxError as exc:
        return {"result": None, "stdout": "", "error": str(exc)}

    try:
        namespace = _build_namespace(dataframes)
    except Exception as exc:  # noqa: BLE001 - report, never raise out
        return {"result": None, "stdout": "", "error": str(exc)}

    try:
        compiled = compile(tree, filename="<sandbox>", mode="exec")
    except Exception as exc:  # noqa: BLE001
        return {"result": None, "stdout": "", "error": str(exc)}

    # --- 2. execute in a worker thread with a wall-clock timeout -----------
    outcome: dict[str, Any] = {"result": None, "stdout": "", "error": None}
    stdout_buffer = io.StringIO()

    def _worker() -> None:
        try:
            with contextlib.redirect_stdout(stdout_buffer):
                exec(compiled, namespace)  # noqa: S102 - restricted namespace
            outcome["result"] = namespace.get("result")
        except BaseException:  # noqa: BLE001 - capture EVERYTHING, never crash
            outcome["error"] = traceback.format_exc()
        finally:
            outcome["stdout"] = stdout_buffer.getvalue()

    worker = threading.Thread(target=_worker, daemon=True)
    worker.start()
    worker.join(timeout)

    if worker.is_alive():
        # Cannot forcibly kill a Python thread; leave it daemon so it cannot
        # block process exit, and report the timeout as a failed attempt.
        return {
            "result": None,
            "stdout": stdout_buffer.getvalue(),
            "error": (
                f"timeout: execution exceeded {timeout}s wall-clock limit"
            ),
        }

    return outcome
