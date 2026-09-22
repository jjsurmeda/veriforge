"""Dump the OpenAPI schema to a file for the web codegen pipeline."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from main import app

OUT = Path(__file__).resolve().parents[1] / ".." / "web" / "openapi.json"


def main() -> None:
    OUT.write_text(json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
