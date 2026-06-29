"""Run the agent: `uv run python -m src` (from the repo root).

`pyproject.toml` packages `src` as a package, so under `python -m src` the repo
root is on sys.path and modules resolve as `src.api`. But every intra-package
import is bare (`from api import ...`, matching `pythonpath=["src"]` used by the
test path). To make the documented run command boot the same way the tests do,
put the `src` directory itself on sys.path before uvicorn resolves "api:app".
"""

import os
import sys

# Directory containing this file = the `src` package dir.
_SRC_DIR = os.path.dirname(os.path.abspath(__file__))
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

import uvicorn  # noqa: E402

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8001"))
    uvicorn.run("api:app", host="0.0.0.0", port=port, reload=False)
