# Capabilities Index

> One file per capability. Each describes exactly one discrete thing the agent can do.

---

## What Is a Capability?

A single, discrete action or behavior the agent performs (e.g. "execute generated pandas safely against the full data").

## Capabilities in This Project

### Active — Phase 1

| Capability | File |
|-----------|------|
| Upload Dataset | [upload_dataset.md](upload_dataset.md) |
| Answer Question with Executed Code | [answer_question_with_code.md](answer_question_with_code.md) |
| Sandboxed Local Code Execution | [sandboxed_code_execution.md](sandboxed_code_execution.md) |

### Deferred — later phases (labelled stubs in Phase 1)

| Capability | Phase | Notes |
|-----------|-------|-------|
| `auto_profile_dataset` | 2 | Auto-profile columns/types/ranges/missing values on upload |
| `render_chart` | 2 | Auto-pick chart type; emit interactive Vega-Lite spec with locally-computed data |
| `suggest_followups` | 2 | Suggest 2–3 follow-up questions after each answer |
| `conversational_followup` | 2 | Carry conversation history so "now break that down by region" resolves in context |
| `multi_file_analysis` | 3 | Join/compare across multiple loaded files |
| `dataset_library` | 3 | Browsable, cross-day persistence of uploaded datasets |
| `cost_tracking` | 3 | Per-question tokens/cost + running daily total from Gemini usage metadata |
| `stream_progress` | 3 | Live SSE step updates ("Planning… Running code…") |
| `run_history` | 3 | Browsable audit trail of question/code/result/timestamps |

> Deferred capabilities get their own `spec/capabilities/<name>.md` when their phase is built. They are listed here so the scope is visible; Phase 1 ships them as clearly-labelled non-functional UI stubs.

## How to Add a New Capability

Run `/zero-shot-build [description]` on the existing spec. The spec-writer will create the file, update this index, flag dependencies, and self-review against the architecture + data model.
