"""Fail when first-party statement coverage is not strictly above 80%.

Coverage.py's ``fail_under`` uses the combined line+branch percentage whenever
branch data was collected (``--cov-branch``). This gate reads
``percent_statements_covered`` so the required bar is statement coverage.

Usage:
    AUTO_START_FRONTEND=0 python -m pytest --cov=. --cov-report=json:coverage.json
    python tests/check_statement_coverage.py coverage.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


MINIMUM_EXCLUSIVE = 80.0


def statement_percent(payload: dict) -> tuple[int, int, float]:
    totals = payload["totals"]
    covered = int(totals["covered_lines"])
    statements = int(totals["num_statements"])
    if statements <= 0:
        return covered, statements, 0.0
    return covered, statements, covered / statements * 100


def main(argv: list[str]) -> int:
    path = Path(argv[1] if len(argv) > 1 else "coverage.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    covered, statements, percent = statement_percent(payload)
    print(f"statement coverage: {covered}/{statements} = {percent:.4f}%")
    if percent <= MINIMUM_EXCLUSIVE:
        print(
            "coverage gate failed: first-party statement coverage must be "
            f"strictly above {MINIMUM_EXCLUSIVE:.0f}%",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
