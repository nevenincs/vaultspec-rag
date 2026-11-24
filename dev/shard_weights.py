"""Rewrite the suite's shard weights from measured runs.

Usage: ``python -m dev.shard_weights DIRECTORY``, where *DIRECTORY* holds the
JUnit reports of one full run of the accelerator-free suite, one report per
shard. A file's weight is the seconds its tests took, and only the files heavy
enough to unbalance a shard are kept; every other file is spread by its name.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from xml.etree import ElementTree

#: A file lighter than this many seconds is left to the spread by name.
_FLOOR_SECONDS = 5.0

_WEIGHTS = Path(__file__).resolve().parent.parent / (
    "src/vaultspec_rag/tests/_shard_weights.json"
)


def _file_of(classname: str) -> str:
    """Return the test file a JUnit ``classname`` names, with forward slashes."""
    parts = classname.split(".")
    for position, part in enumerate(parts):
        if part.startswith("test_"):
            return "/".join(parts[: position + 1]) + ".py"
    return "/".join(parts) + ".py"


def measured(directory: Path) -> dict[str, float]:
    """Return each heavy test file's seconds across the reports in *directory*."""
    seconds: defaultdict[str, float] = defaultdict(float)
    for report in sorted(directory.rglob("*.xml")):
        for case in ElementTree.parse(report).getroot().iter("testcase"):
            seconds[_file_of(case.get("classname", ""))] += float(
                case.get("time") or 0.0
            )
    return {
        name: round(spent, 1)
        for name, spent in sorted(seconds.items())
        if spent >= _FLOOR_SECONDS
    }


def main() -> None:
    weights = measured(Path(sys.argv[1]))
    _WEIGHTS.write_text(json.dumps(weights, indent=2) + "\n", encoding="utf-8")
    print(f"{len(weights)} weighted file(s) written to {_WEIGHTS}")


if __name__ == "__main__":
    main()
