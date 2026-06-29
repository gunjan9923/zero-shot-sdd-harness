# Capability: Answer Question with Executed Code

## What It Does
Given a question about a loaded dataset, the agent plans an approach, generates pandas code via Gemini (using schema + samples only), executes that code locally in a restricted sandbox against the FULL DataFrame, auto-retries on failure, and returns a plain-language answer with the exact code that ran.

## Inputs
| Input | Type | Source | Required |
|-------|------|--------|----------|
| dataset_id | str | `POST /analyses` | yes |
| question | str | `POST /analyses` | yes |
| messages | list (prior turns) | runner (from prior analyses) | no (Phase 2 follow-ups) |
| schema, samples | JSON | loaded from `datasets` | yes (LLM-visible context) |

## Outputs
| Output | Type | Destination |
|--------|------|-------------|
| answer | str (plain-language + numbers) | response + `analyses.answer` |
| code | str (exact pandas that ran) | response + `analyses.code` (collapsible UI panel) |
| plan | str | response + `analyses.plan` |
| result | JSON (computed value/table) | response + `analyses.result_json` |
| retry_count | int | response + `analyses.retry_count` |
| status | `completed`/`failed` | `analyses.status` |

## External Calls
| System | Operation | On Failure |
|--------|-----------|------------|
| Gemini | plan, generate code, phrase answer | retry/backoff → set `error` → `failed` |
| Execution sandbox | run pandas vs full DataFrame | capture error → reflect/retry; exhausted → `failed` |

## Business Rules
- Only schema + bounded samples are sent to Gemini — never raw rows (privacy boundary).
- Generated code must assign its answer to `result`; it runs against the FULL DataFrame, not the samples — so the answer reflects all rows.
- On code exception / empty / all-NaN result, regenerate code with the error context, bounded by `AGENT_MAX_RETRIES` (default 2); after that, fail gracefully and still surface the last code tried.
- The answer states the key numbers explicitly and matches a hand-computed pandas result on the full file.

## Success Criteria
- [ ] For a known fixture, the returned numeric answer exactly equals the full-data pandas computation (tested on a file large enough — ≥200k rows — that a sample-based answer would differ).
- [ ] The `code` returned is the exact snippet executed and is valid runnable pandas.
- [ ] When the first generated snippet raises, `retry_count` ≥ 1 and the final answer is still correct.
- [ ] No raw data row appears in the logged Gemini prompt payload (only schema + samples).
- [ ] A question that cannot be answered after `max_retries` returns `status="failed"` with a clear message and the last attempted code.
