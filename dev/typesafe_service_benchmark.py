"""Capture identical real-service searches for a classifier off/on comparison.

This client never loads models, changes server enrollment, or supplies API keys.
Start/restart the service separately with the intended environment. Output files
are exclusive-create so an earlier measurement cannot be silently overwritten.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import cast

from typesafe_evaluation import CANDIDATES, CASES, ROOT

from vaultspec_rag.serviceclient._search_transport import try_http_search


def object_map(value: object) -> dict[str, object]:
    return cast("dict[str, object]", value) if isinstance(value, dict) else {}


def rows(payload: dict[str, object]) -> list[dict[str, object]]:
    value = payload.get("results")
    if not isinstance(value, list):
        return []
    return [object_map(row) for row in cast("list[object]", value)]


def classification_metrics(value: object) -> dict[str, float]:
    found: dict[str, float] = {}
    for key, item in object_map(value).items():
        if key.startswith("typesafe_") or key == "classification_fallback":
            if isinstance(item, (float, int)) and not isinstance(item, bool):
                found[key] = float(item)
        elif isinstance(item, dict):
            found.update(classification_metrics(cast("dict[str, object]", item)))
    return found


def redact_credentials(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: redact_credentials(item)
            for key, item in cast("dict[str, object]", value).items()
            if key not in {"service_token", "launch_token", "api_key", "authorization"}
        }
    if isinstance(value, list):
        return [redact_credentials(item) for item in cast("list[object]", value)]
    return value


def capture(
    query: str, port: int, freshness_policy: str
) -> tuple[dict[str, object], float]:
    started = time.perf_counter()
    payload: dict[str, object] | None = try_http_search(
        query,
        "code",
        15,
        port,
        str(ROOT),
        include_paths=["src/vaultspec_rag"],
        freshness_policy=freshness_policy,
        freshness_wait_seconds=30.0 if freshness_policy == "bounded" else None,
        timeout=300.0,
    )
    elapsed = time.perf_counter() - started
    if payload is None:
        payload = {"ok": False, "error": "connection_refused"}
    return payload, elapsed


def manifest() -> dict[str, object]:
    subprocess.run(
        ["git", "diff", "--exit-code", "HEAD", "--", "src/vaultspec_rag"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    anchors: list[dict[str, object]] = []
    for index, candidate in enumerate(CANDIDATES):
        result = candidate.result(index)
        anchors.append(
            {
                **asdict(candidate),
                "line_start": result.line_start,
                "line_end": result.line_end,
                "content_sha256": hashlib.sha256(
                    (result.rerank_text or "").encode()
                ).hexdigest(),
            }
        )
    return {
        "head": head,
        "root": str(ROOT),
        "type": "code",
        "top_k": 15,
        "include_paths": ["src/vaultspec_rag"],
        "repetitions": 3,
        "queries": [asdict(case) for case in CASES],
        "anchors": anchors,
        "warmup": "hybrid semantic code search candidate retrieval",
    }


def anchor_positions(
    results: list[dict[str, object]], names: tuple[str, ...]
) -> dict[str, int | None]:
    targets = {candidate.id: candidate for candidate in CANDIDATES}
    return {
        name: next(
            (
                rank
                for rank, row in enumerate(results, 1)
                if str(row.get("path", "")).replace("\\", "/") == targets[name].path
                and row.get("function_name") == targets[name].function
            ),
            None,
        )
        for name in names
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("off", "on"), required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--freshness-policy", choices=("immediate", "bounded"), default="immediate"
    )
    args = parser.parse_args()
    output = cast("Path", args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    protocol = manifest()
    protocol["freshness_policy"] = args.freshness_policy
    manifest_path = output / "manifest.json"
    serialized = json.dumps(protocol, indent=2, sort_keys=True)
    if manifest_path.exists():
        if manifest_path.read_text(encoding="utf-8") != serialized:
            raise RuntimeError("benchmark protocol or code changed between arms")
    else:
        with manifest_path.open("x", encoding="utf-8") as stream:
            stream.write(serialized)
    measurements: list[dict[str, object]] = []
    status = subprocess.run(
        [
            sys.executable,
            "-B",
            "-m",
            "vaultspec_rag",
            "server",
            "status",
            "--port",
            str(args.port),
            "--json",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    with (output / f"{args.mode}-service-status.json").open(
        "x", encoding="utf-8"
    ) as snapshot:
        snapshot.write(
            json.dumps(redact_credentials(json.loads(status.stdout)), indent=2)
        )
    with (output / f"{args.mode}.jsonl").open("x", encoding="utf-8") as stream:
        warmup, elapsed = capture(
            str(protocol["warmup"]), args.port, args.freshness_policy
        )
        stream.write(
            json.dumps(
                {
                    "kind": "warmup",
                    "freshness_policy": args.freshness_policy,
                    "wall_seconds": elapsed,
                    "response": warmup,
                }
            )
            + "\n"
        )
        stream.flush()
        if warmup.get("ok") is False:
            print(json.dumps({"error": "warmup_failed", "response": warmup}))
            return 1
        for repeat in range(3):
            for case in CASES:
                payload, elapsed = capture(case.query, args.port, args.freshness_policy)
                result_rows = rows(payload)
                metrics = classification_metrics(payload)
                record: dict[str, object] = {
                    "kind": "measurement",
                    "mode": args.mode,
                    "freshness_policy": args.freshness_policy,
                    "repeat": repeat,
                    "case": case.name,
                    "query": case.query,
                    "wall_seconds": elapsed,
                    "result_count": len(result_rows),
                    "anchor_positions": anchor_positions(result_rows, case.relevant),
                    "classification": metrics,
                    "response": payload,
                }
                stream.write(json.dumps(record) + "\n")
                stream.flush()
                measurements.append(record)
                print(
                    json.dumps(
                        {
                            key: value
                            for key, value in record.items()
                            if key not in {"response", "query"}
                        }
                    ),
                    flush=True,
                )
                if payload.get("ok") is False:
                    return 1
    elapsed_values = [float(cast("float", row["wall_seconds"])) for row in measurements]
    print(
        json.dumps(
            {
                "mode": args.mode,
                "searches": len(measurements),
                "median_wall_seconds": statistics.median(elapsed_values),
                "max_wall_seconds": max(elapsed_values),
                "total_wall_seconds": sum(elapsed_values),
            }
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
