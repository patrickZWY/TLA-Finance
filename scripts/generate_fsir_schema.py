"""Generate the checked-in FSIR v0.1 JSON Schema from Pydantic models."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from safety.fsir import fsir_json_schema  # noqa: E402


DEFAULT_OUTPUT = ROOT / "docs" / "fsir-v0.1.schema.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(fsir_json_schema(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote FSIR schema to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
