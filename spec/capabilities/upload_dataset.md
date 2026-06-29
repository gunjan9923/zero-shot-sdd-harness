# Capability: Upload Dataset

## What It Does
Accepts a CSV/Excel file upload, stores it locally, loads it once to extract an LLM-safe schema and bounded sample rows, and records a persistent `datasets` row.

## Inputs
| Input | Type | Source | Required |
|-------|------|--------|----------|
| file | multipart file (CSV or .xlsx) | browser upload (`POST /datasets`) | yes |

## Outputs
| Output | Type | Destination |
|--------|------|-------------|
| dataset_id | str (uuid) | API response + `datasets` table |
| schema | JSON `{column: dtype}` | response + `datasets.schema_json` |
| samples | JSON (bounded sample rows, default 5) | response + `datasets.samples_json` |
| row_count | int | response + `datasets.row_count` |
| stored file | local file | `./data/uploads/` + `datasets.file_path` |

## External Calls
| System | Operation | On Failure |
|--------|-----------|------------|
| Local filesystem | write uploaded file | 500 with message |
| pandas/openpyxl | load file, infer dtypes, take samples | 400 "could not parse" |

## Business Rules
- Only `csv` and `xlsx` accepted; other types rejected with 400.
- Files up to ~100MB are loaded fully into an in-memory DataFrame; reject larger with 400.
- Only column names, dtypes, and a bounded number of sample rows are extracted for LLM use — raw rows are never put anywhere the LLM can see.
- `row_count` is the true full count (not the sample).

## Success Criteria
- [ ] Uploading a valid CSV returns a `dataset_id`, the correct `row_count`, the full column→dtype schema, and exactly `AGENT_SAMPLE_ROWS` (default 5) sample rows.
- [ ] The stored file exists under `./data/uploads/` and the `datasets` row references it.
- [ ] Uploading a non-CSV/non-xlsx or an unparseable file returns 400 with a clear message.
- [ ] The structured log for the upload contains no full-data dump — only schema + samples.
