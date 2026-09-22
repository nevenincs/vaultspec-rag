"""Live production classification over saved retrieval hits, without GPU work.

Fresh closes every completed connection; warm retains pooled sockets but clears
answer caches; cached repeats the preceding request without clearing either.
No provider response is mocked. This is not an end-to-end service benchmark.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, nullcontext
from pathlib import Path
from threading import Barrier
from typing import TYPE_CHECKING, TypedDict, cast
from unittest.mock import patch

from typesafe_evaluation import ROOT

from vaultspec_rag.config._types import EnvVar
from vaultspec_rag.search import _typesafe_transport as transport
from vaultspec_rag.search._models import SearchResult
from vaultspec_rag.search._typesafe_cache import ResponseCache
from vaultspec_rag.search._typesafe_policy import prepare_query
from vaultspec_rag.search._typesafe_pool import ConnectionPool
from vaultspec_rag.search._typesafe_questions import query_questions

if TYPE_CHECKING:
    from vaultspec_rag.search._typesafe_pool import ConnectionLease


class Hit(TypedDict):
    id: str
    path: str
    score: float
    line_start: int
    line_end: int


class Response(TypedDict):
    results: list[Hit]


class SavedRow(TypedDict):
    case: str
    query: str
    repeat: int
    kind: str
    response: Response


def candidates(case: SavedRow, rows: list[SavedRow]) -> list[SearchResult]:
    hits: dict[str, Hit] = {}
    for row in [case, *rows]:
        for hit in row["response"]["results"]:
            hits.setdefault(hit["id"], hit)
    results: list[SearchResult] = []
    for hit in list(hits.values())[:32]:
        path = (ROOT / hit["path"]).resolve()
        if not path.is_relative_to(ROOT):
            raise ValueError("fixture path outside checkout")
        lines = path.read_text(encoding="utf-8").splitlines()
        results.append(
            SearchResult(
                id=hit["id"],
                path=hit["path"],
                title="",
                score=hit["score"],
                snippet="unused",
                source="codebase",
                rerank_text="\n".join(lines[hit["line_start"] - 1 : hit["line_end"]]),
            )
        )
    return results


def discard(lease: ConnectionLease, *, reusable: bool) -> None:
    del reusable
    lease.connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if not os.environ.get(EnvVar.TYPESAFE_API_KEY, "").strip():
        raise RuntimeError("dedicated live credential required")
    fixture = cast("Path", args.fixture)
    output = cast("Path", args.output)
    rows = [
        cast("SavedRow", json.loads(line)) for line in fixture.read_text().splitlines()
    ]
    rows = [
        row
        for row in rows
        if row.get("kind") == "measurement" and row.get("repeat") == 0
    ]
    selected = [
        row
        for row in rows
        if row["case"]
        in {
            "hybrid_fusion",
            "status_and_noise",
            "grouping_and_order",
        }
    ]
    if len(selected) != 3:
        raise ValueError("expected three saved query fixtures")
    pool, cache = ConnectionPool(), ResponseCache()
    with ExitStack() as stack, output.open("x", encoding="utf-8") as stream:
        stack.enter_context(patch.object(transport, "_POOL", pool))
        stack.enter_context(patch.object(transport, "_CACHE", cache))
        stack.callback(pool.close)
        for repeat in range(2):
            for case in selected:
                results = candidates(case, rows)
                modes = (
                    ("fresh", "warm", "cached")
                    if repeat == 0
                    else ("warm", "cached", "fresh")
                )
                for mode in modes:
                    if mode != "cached":
                        cache.clear()
                    if mode == "fresh":
                        pool.close()
                    context = (
                        patch.object(pool, "release", discard)
                        if mode == "fresh"
                        else nullcontext()
                    )
                    with context:
                        started = time.perf_counter()
                        session = prepare_query(
                            case["query"],
                            "code",
                            {"include_paths": ["src/vaultspec_rag"]},
                        )
                        if session is None:
                            raise RuntimeError("live query classification unavailable")
                        ranked = session.rank(results)
                        record = {
                            "case": case["case"],
                            "query": case["query"],
                            "repeat": repeat,
                            "mode": mode,
                            "classification_ms": (time.perf_counter() - started) * 1000,
                            "candidate_count": len(results),
                            "returned_ids": [result.id for result in ranked],
                            "timings": session.timings,
                        }
                    encoded = json.dumps(record)
                    stream.write(encoded + "\n")
                    stream.flush()
                    print(encoded, flush=True)
        cache.clear()
        barrier = Barrier(4)

        def duplicate() -> tuple[int, int, int]:
            barrier.wait(timeout=2)
            answer = transport.evaluate(
                {"query": selected[0]["query"]}, query_questions()
            )
            return answer.requests, answer.coalesced, answer.cache_hits

        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(duplicate) for _ in range(4)]
            counts = [future.result() for future in futures]
        record = {
            "case": "concurrent_query",
            "mode": "coalesced",
            "classification_ms": (time.perf_counter() - started) * 1000,
            "requests": sum(row[0] for row in counts),
            "coalesced": sum(row[1] for row in counts),
            "cache_hits": sum(row[2] for row in counts),
        }
        encoded = json.dumps(record)
        stream.write(encoded + "\n")
        print(encoded, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
