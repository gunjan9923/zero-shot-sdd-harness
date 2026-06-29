# Capability: Sandboxed Local Code Execution

## What It Does
Executes LLM-generated pandas code locally against the full in-memory DataFrame inside a restricted sandbox that blocks network, filesystem writes, dangerous builtins, and disallowed imports — capturing the result, stdout, and any error without letting untrusted code do harm.

## Inputs
| Input | Type | Source | Required |
|-------|------|--------|----------|
| code | str (pandas snippet assigning `result`) | `generate_code` node | yes |
| df / dfs | pandas DataFrame(s) | dataset loader (full data, in-memory) | yes |
| timeout_s | int | `AGENT_EXEC_TIMEOUT_S` (default 25) | no |

## Outputs
| Output | Type | Destination |
|--------|------|-------------|
| result | object (the value assigned to `result`) | `AgentState.exec_result` |
| stdout | str | `AgentState.exec_stdout` |
| error | str \| None (traceback/timeout) | `AgentState.exec_error` (drives retry) |

## External Calls
| System | Operation | On Failure |
|--------|-----------|------------|
| RestrictedPython (or AST allow-list) | compile + restrict the snippet | reject → return as `error` (no exec) |
| (none — no network/fs) | — | — |

## Business Rules
- Allowed imports only: `pandas`, `numpy`, `math`, `datetime`, `statistics`. Everything else (`os`, `sys`, `subprocess`, `open`, `eval`, `exec`, `__import__`, dunder attribute access) is denied.
- The exec namespace exposes only `pd`, `np`, the DataFrame(s) (`df`/`dfs`), and a curated safe-builtins set; no filesystem or network names are bound.
- No filesystem writes (no `to_csv`/`open`) and no network access from generated code.
- A copy of the DataFrame is passed in (source data is read-only).
- A wall-clock timeout terminates a runaway snippet; timeout is reported as an error (treated as a failed attempt, drives retry).
- Exceptions are captured and returned, never raised out of the sandbox.

## Success Criteria
- [ ] A valid snippet (`result = df['amount'].sum()`) returns the correct value over the full DataFrame with no error.
- [ ] A snippet attempting `import os` / `open(...)` / network access is rejected or fails inside the sandbox with `error` set and no side effect (no file written, no socket opened).
- [ ] A snippet that raises has its traceback captured in `error` with `result` unset — never crashes the process.
- [ ] A snippet exceeding the timeout is terminated and reported as an error within ~timeout_s.
