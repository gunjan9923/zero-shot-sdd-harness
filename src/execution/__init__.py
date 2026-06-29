"""Local execution layer: dataset loading + restricted pandas sandbox.

This package keeps the two surfaces that touch local data:

- ``loader``  — read a CSV/Excel file into a pandas DataFrame and derive the
  LLM-safe schema + bounded sample rows (the privacy boundary).
- ``sandbox`` — run LLM-generated pandas in a restricted namespace with an
  import allow-list, a builtins denylist, and a wall-clock timeout.
"""

from execution.loader import (
    dataframe_cache,
    extract_samples,
    extract_schema,
    get_or_load,
    load_dataset,
)
from execution.sandbox import run_pandas

__all__ = [
    "run_pandas",
    "load_dataset",
    "extract_schema",
    "extract_samples",
    "get_or_load",
    "dataframe_cache",
]
