"""Tests for the restricted pandas execution sandbox.

The denylist (no os/sys/subprocess/open/eval/exec/__import__, no dunders, only
allow-listed imports) is the security boundary — these tests verify it directly.
No network or LLM is needed here.
"""

from __future__ import annotations

import os

import pandas as pd
import pytest

from execution.sandbox import run_pandas


@pytest.fixture
def df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "amount": [10, 20, 30, 40],
            "region": ["n", "s", "n", "e"],
        }
    )


# --- happy path --------------------------------------------------------------


def test_valid_snippet_returns_correct_value(df):
    out = run_pandas("result = df['amount'].sum()", {"df": df})
    assert out["error"] is None
    assert out["result"] == 100
    assert out["stdout"] == ""


def test_print_is_captured_in_stdout(df):
    out = run_pandas(
        "print('hello'); result = len(df)",
        {"df": df},
    )
    assert out["error"] is None
    assert out["result"] == 4
    assert "hello" in out["stdout"]


def test_allowed_import_numpy_groupby(df):
    code = "import numpy as np\nresult = int(np.sum(df['amount'].to_numpy()))"
    out = run_pandas(code, {"df": df})
    assert out["error"] is None
    assert out["result"] == 100


def test_source_dataframe_is_not_mutated(df):
    before = df["amount"].sum()
    code = "df['amount'] = 0\nresult = df['amount'].sum()"
    out = run_pandas(code, {"df": df})
    # Inside the sandbox the copy was zeroed...
    assert out["result"] == 0
    # ...but the caller's DataFrame is untouched (a copy was passed in).
    assert df["amount"].sum() == before


# --- edge case: empty input --------------------------------------------------


def test_empty_dataframe_no_crash():
    empty = pd.DataFrame({"amount": []})
    out = run_pandas("result = df['amount'].sum()", {"df": empty})
    assert out["error"] is None
    assert out["result"] == 0  # pandas sum of empty is 0.0 -> equals 0


# --- security: imports / fs / network are blocked ----------------------------


def test_import_os_is_rejected_no_side_effect(tmp_path):
    target = tmp_path / "pwned_import_os.txt"
    code = (
        "import os\n"
        f"open(r'{target}', 'w').write('x')\n"
        "result = 1"
    )
    out = run_pandas(code, {"df": pd.DataFrame({"a": [1]})})
    assert out["result"] is None
    assert out["error"] is not None
    assert not target.exists()


def test_open_is_rejected_no_file_written(tmp_path):
    target = tmp_path / "pwned_open.txt"
    code = f"result = open(r'{target}', 'w').write('boom')"
    out = run_pandas(code, {"df": pd.DataFrame({"a": [1]})})
    assert out["result"] is None
    assert out["error"] is not None
    assert not target.exists()


def test_socket_import_is_rejected():
    code = "import socket\nresult = socket.socket()"
    out = run_pandas(code, {"df": pd.DataFrame({"a": [1]})})
    assert out["result"] is None
    assert out["error"] is not None


def test_to_csv_write_is_blocked(tmp_path):
    # `df.to_csv(path)` would write a file; the denied name `open` is one vector
    # but to_csv itself uses builtins under the hood. We assert no file appears.
    target = tmp_path / "pwned_to_csv.csv"
    code = f"df.to_csv(r'{target}')\nresult = 1"
    out = run_pandas(code, {"df": pd.DataFrame({"a": [1]})})
    # Whether it errors or not, no write should land via a blocked path. pandas
    # to_csv opens files through its own io layer; this documents the contract:
    # if it DID write, the test will fail and we tighten the boundary.
    # In practice to_csv uses the builtin open, which is not bound -> errors.
    assert out["result"] is None
    assert out["error"] is not None
    assert not target.exists()


def test_dunder_attribute_access_rejected():
    code = "result = df.__class__.__mro__"
    out = run_pandas(code, {"df": pd.DataFrame({"a": [1]})})
    assert out["result"] is None
    assert out["error"] is not None


def test_eval_and_exec_rejected():
    for snippet in ("result = eval('1+1')", "exec('result = 1')"):
        out = run_pandas(snippet, {"df": pd.DataFrame({"a": [1]})})
        assert out["result"] is None
        assert out["error"] is not None


def test_dunder_import_rejected():
    code = "result = __import__('os')"
    out = run_pandas(code, {"df": pd.DataFrame({"a": [1]})})
    assert out["result"] is None
    assert out["error"] is not None


# --- error path: runtime exceptions are captured -----------------------------


def test_runtime_error_captured_in_error(df):
    out = run_pandas("result = df['missing'].sum()", {"df": df})
    assert out["result"] is None
    assert out["error"] is not None
    assert "KeyError" in out["error"] or "missing" in out["error"]


def test_syntax_error_captured():
    out = run_pandas("result = (", {"df": pd.DataFrame({"a": [1]})})
    assert out["result"] is None
    assert out["error"] is not None
    assert "SyntaxError" in out["error"]


# --- timeout -----------------------------------------------------------------


def test_timeout_returns_error_quickly(df):
    out = run_pandas("while True:\n    pass", {"df": df}, timeout_s=2)
    assert out["result"] is None
    assert out["error"] is not None
    assert "timeout" in out["error"].lower()


def test_timeout_env_var_default(monkeypatch, df):
    monkeypatch.setenv("AGENT_EXEC_TIMEOUT_S", "1")
    out = run_pandas("while True:\n    pass", {"df": df})
    assert out["result"] is None
    assert "timeout" in (out["error"] or "").lower()


def test_no_env_uses_arg(monkeypatch, df):
    monkeypatch.delenv("AGENT_EXEC_TIMEOUT_S", raising=False)
    out = run_pandas("result = df['amount'].sum()", {"df": df})
    assert out["error"] is None
    assert out["result"] == 100


def test_no_files_left_behind_in_cwd():
    # Sanity: a normal run must not create stray files in the working directory.
    before = set(os.listdir("."))
    run_pandas("result = 1", {"df": pd.DataFrame({"a": [1]})})
    after = set(os.listdir("."))
    assert before == after
