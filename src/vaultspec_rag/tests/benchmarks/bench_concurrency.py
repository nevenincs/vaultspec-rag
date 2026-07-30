"""Adversarial concurrency benchmark for the resident RAG service.

Drives N parallel ``POST /search`` requests against a *live* service
(same-root, cross-root, vault+code mixed, optionally while a reindex
job runs) and reports throughput, latency percentiles, and the
service's own per-phase timings (embedding, qdrant, rerank, GPU queue
wait, project lease). This benchmark freezes the pre-rework baseline
and re-measures after every wave.

Run standalone (service must be running):

    uv run python -m vaultspec_rag.tests.benchmarks.bench_concurrency \
        --root /projects/main \
        --root /projects/another \
        --requests 32 --concurrency 8 --json results.json

Not collected by pytest (no ``test_`` functions): saturating a live
shared service is an operator action, not a unit-test side effect.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

if TYPE_CHECKING:
    from http.client import HTTPResponse

    # ``argparse.Namespace`` attribute access is unavoidably ``Any`` (the
    # parser has no static view of what ``add_argument`` calls produced).
    # This mirrors main()'s declared arguments so a single cast replaces
    # every per-attribute ``Any`` read below it.
    class _ParsedArgs(Protocol):
        root: list[str]
        requests: int
        concurrency: int
        top_k: int
        timeout: float
        with_reindex: bool
        json: Path | None


__all__ = [
    "RequestOutcome",
    "ScenarioResult",
    "ServiceTarget",
    "build_scenarios",
    "run_scenario",
]

#: Phase keys aggregated from the search route's ``timing`` payload.
_PHASE_KEYS = (
    "embedding_seconds",
    "qdrant_seconds",
    "rerank_seconds",
    "postprocess_seconds",
    "project_lease_seconds",
    "server_total_seconds",
)

#: Extra keys nested under ``timing.phases``.
_NESTED_PHASE_KEYS = ("gpu_queue_wait_seconds", "queue_wait_seconds")

_QUERIES = (
    "how does the watcher debounce and cooldown work",
    "gpu lock serialization during search and indexing",
    "qdrant hybrid search with sparse vectors",
    "service registry project slot eviction",
    "incremental index content hashing",
    "cross encoder reranker batch size",
    "error handling for locked local store",
    "capacity limits for concurrent requests",
)


@dataclass
class ServiceTarget:
    """Connection coordinates for the running service."""

    port: int
    token: str

    @classmethod
    def discover(cls) -> ServiceTarget:
        """Read port + token from the service.json the daemon maintains.

        Raises:
            RuntimeError: If service.json is missing or incomplete.
        """
        from ...config._settings import get_config

        cfg = get_config()
        path = Path(str(cast("object", cfg.status_dir))).expanduser() / "service.json"
        try:
            data = cast(
                "dict[str, object]",
                json.loads(path.read_text(encoding="utf-8")),
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"Cannot read {path}: is the service running? ({exc})",
            ) from exc
        # ``int()``/``str()`` already coerce (and raise on a genuinely bad
        # value) at runtime; the cast only asserts the JSON-decoded shape
        # service.json is documented to carry, same as the pre-existing
        # runtime behaviour.
        port = int(cast("int | float | str", data.get("port", 0)))
        token = str(data.get("service_token", data.get("token", "")))
        if not port:
            raise RuntimeError(f"service.json at {path} carries no port")
        return cls(port=port, token=token)

    def post(
        self,
        path: str,
        payload: dict[str, object],
        timeout: float,
    ) -> dict[str, object]:
        """POST JSON and decode the JSON response."""
        url = f"http://127.0.0.1:{self.port}{path}"
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        # urlopen()'s return is typed Any upstream (it dispatches across
        # FTP/HTTP/file handlers); this request is always http://, so the
        # concrete response type is genuinely HTTPResponse.
        opened = cast("HTTPResponse", urllib.request.urlopen(req, timeout=timeout))
        with opened as resp:
            # The service's response shape is only a contract at the JSON
            # boundary; decode it once here and let every caller narrow the
            # specific keys it reads instead of carrying `Any` outward.
            return cast("dict[str, object]", json.loads(resp.read().decode("utf-8")))


@dataclass
class RequestOutcome:
    """One request's client-side latency and server-side phase timings."""

    latency_seconds: float
    ok: bool
    error: str | None = None
    phases: dict[str, float] = field(default_factory=dict)


@dataclass
class ScenarioResult:
    """Aggregated metrics for one saturation scenario."""

    name: str
    concurrency: int
    requests: int
    wall_seconds: float
    outcomes: list[RequestOutcome]

    @property
    def ok_count(self) -> int:
        return sum(1 for o in self.outcomes if o.ok)

    @property
    def error_count(self) -> int:
        return len(self.outcomes) - self.ok_count

    @property
    def throughput_rps(self) -> float:
        return self.ok_count / self.wall_seconds if self.wall_seconds > 0 else 0.0

    def latency_percentiles(self) -> dict[str, float]:
        """Return p50/p95/max client-observed latency over OK requests."""
        latencies = sorted(o.latency_seconds for o in self.outcomes if o.ok)
        if not latencies:
            return {"p50": 0.0, "p95": 0.0, "max": 0.0}
        return {
            "p50": _percentile(latencies, 0.50),
            "p95": _percentile(latencies, 0.95),
            "max": latencies[-1],
        }

    def phase_summary(self) -> dict[str, dict[str, float]]:
        """Mean and max per recorded service phase across OK requests."""
        summary: dict[str, dict[str, float]] = {}
        for key in (*_PHASE_KEYS, *_NESTED_PHASE_KEYS):
            values = [o.phases[key] for o in self.outcomes if o.ok and key in o.phases]
            if values:
                summary[key] = {
                    "mean": statistics.fmean(values),
                    "max": max(values),
                }
        return summary

    def to_dict(self) -> dict[str, object]:
        """JSON-serializable report row."""
        return {
            "name": self.name,
            "concurrency": self.concurrency,
            "requests": self.requests,
            "ok": self.ok_count,
            "errors": self.error_count,
            "wall_seconds": round(self.wall_seconds, 3),
            "throughput_rps": round(self.throughput_rps, 3),
            "latency": {k: round(v, 3) for k, v in self.latency_percentiles().items()},
            "phases": {
                key: {stat: round(v, 4) for stat, v in stats.items()}
                for key, stats in self.phase_summary().items()
            },
        }


def _percentile(sorted_values: list[float], q: float) -> float:
    """Nearest-rank percentile over an already sorted list."""
    if not sorted_values:
        return 0.0
    rank = max(0, min(len(sorted_values) - 1, round(q * (len(sorted_values) - 1))))
    return sorted_values[rank]


def _extract_phases(timing: object) -> dict[str, float]:
    """Flatten the route's timing dict into the tracked phase keys."""
    phases: dict[str, float] = {}
    if not isinstance(timing, dict):
        return phases
    timing_map = cast("dict[str, object]", timing)
    for key in _PHASE_KEYS:
        value = timing_map.get(key)
        if isinstance(value, (int, float)):
            phases[key] = float(value)
    nested = timing_map.get("phases")
    if isinstance(nested, dict):
        nested_map = cast("dict[str, object]", nested)
        for key in _NESTED_PHASE_KEYS:
            value = nested_map.get(key)
            if isinstance(value, (int, float)):
                phases[key] = float(value)
    return phases


def _one_request(
    target: ServiceTarget,
    payload: dict[str, object],
    timeout: float,
) -> RequestOutcome:
    started = time.perf_counter()
    try:
        body = target.post("/search", payload, timeout)
    except Exception as exc:
        return RequestOutcome(
            latency_seconds=time.perf_counter() - started,
            ok=False,
            error=f"{exc.__class__.__name__}: {exc}",
        )
    latency = time.perf_counter() - started
    if "results" not in body:
        return RequestOutcome(
            latency_seconds=latency,
            ok=False,
            error=str(body.get("error", "no_results_key")),
        )
    return RequestOutcome(
        latency_seconds=latency,
        ok=True,
        phases=_extract_phases(body.get("timing")),
    )


def run_scenario(
    target: ServiceTarget,
    name: str,
    payloads: list[dict[str, object]],
    concurrency: int,
    timeout: float,
) -> ScenarioResult:
    """Fire all payloads through a bounded thread pool and aggregate."""
    started = time.perf_counter()

    def _run(payload: dict[str, object]) -> RequestOutcome:
        return _one_request(target, payload, timeout)

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        outcomes = list(pool.map(_run, payloads))
    wall = time.perf_counter() - started
    return ScenarioResult(
        name=name,
        concurrency=concurrency,
        requests=len(payloads),
        wall_seconds=wall,
        outcomes=outcomes,
    )


def _payload(root: str, search_type: str, query: str, top_k: int) -> dict[str, object]:
    return {
        "type": search_type,
        "query": query,
        "top_k": top_k,
        "project_root": root,
    }


def _cycle_payloads(
    roots: list[str],
    search_types: list[str],
    n_requests: int,
    top_k: int,
) -> list[dict[str, object]]:
    payloads: list[dict[str, object]] = []
    for i in range(n_requests):
        root = roots[i % len(roots)]
        # Advance the type cycle once per full root cycle so equal-length
        # lists do not run in lockstep (which would pin each root to a
        # single search type and miss whole combinations).
        search_type = search_types[(i // len(roots)) % len(search_types)]
        query = _QUERIES[i % len(_QUERIES)]
        payloads.append(_payload(root, search_type, query, top_k))
    return payloads


def build_scenarios(
    roots: list[str],
    n_requests: int,
    top_k: int,
) -> list[tuple[str, list[dict[str, object]]]]:
    """Build the saturation matrix for the given project roots.

    Same-root vault, same-root code, and same-root mixed always run
    against the first root; the cross-root scenarios appear only when
    two or more roots are supplied.
    """
    primary = roots[0]
    scenarios: list[tuple[str, list[dict[str, object]]]] = [
        (
            "same-root-vault",
            _cycle_payloads([primary], ["vault"], n_requests, top_k),
        ),
        (
            "same-root-code",
            _cycle_payloads([primary], ["codebase"], n_requests, top_k),
        ),
        (
            "same-root-mixed",
            _cycle_payloads([primary], ["vault", "codebase"], n_requests, top_k),
        ),
    ]
    if len(roots) > 1:
        scenarios.append(
            (
                "cross-root-mixed",
                _cycle_payloads(roots, ["vault", "codebase"], n_requests, top_k),
            ),
        )
    return scenarios


def _start_reindex(target: ServiceTarget, root: str, timeout: float) -> str | None:
    """Kick an incremental codebase reindex; return its job id if accepted."""
    try:
        body = target.post(
            "/reindex",
            {
                "type": "codebase",
                "clean": False,
                "project_root": root,
                "initiator_kind": "benchmark",
            },
            timeout,
        )
    except Exception as exc:
        print(f"reindex kick failed: {exc}", file=sys.stderr)
        return None
    job_id = body.get("job_id")
    return str(job_id) if job_id else None


def _print_summary(results: list[ScenarioResult]) -> None:
    # Read straight off the typed `ScenarioResult`, not the JSON-shaped
    # `to_dict()` row: that dict exists for serialization, and subscripting
    # it back out for display would re-widen every field to `object`.
    for result in results:
        latency = result.latency_percentiles()
        print(
            f"{result.name:<24} c={result.concurrency:<3} "
            f"n={result.requests:<4} ok={result.ok_count:<4} "
            f"err={result.error_count:<3} "
            f"rps={round(result.throughput_rps, 3):<7} "
            f"p50={latency['p50']}s p95={latency['p95']}s max={latency['max']}s",
        )
        for key, stats in result.phase_summary().items():
            print(f"    {key:<28} mean={stats['mean']}s max={stats['max']}s")


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for the saturation benchmark."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        action="append",
        required=True,
        help="Project root to search (repeat for cross-root scenarios).",
    )
    parser.add_argument("--requests", type=int, default=32)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument(
        "--with-reindex",
        action="store_true",
        help="Kick an incremental codebase reindex on the first root and "
        "run the matrix while it is in flight.",
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=None,
        help="Write the full machine-readable report to this path.",
    )
    args = cast("_ParsedArgs", parser.parse_args(argv))

    target = ServiceTarget.discover()
    roots: list[str] = [str(Path(r).resolve()) for r in args.root]

    # One warm-up request per root so cold project-lease cost does not
    # pollute the saturation numbers (it is measured separately by the
    # service's own project_lease_seconds phase).
    for root in roots:
        _one_request(
            target,
            _payload(root, "vault", _QUERIES[0], args.top_k),
            args.timeout,
        )

    reindex_job: str | None = None
    if args.with_reindex:
        reindex_job = _start_reindex(target, roots[0], args.timeout)
        print(f"reindex job in flight: {reindex_job}", file=sys.stderr)

    results = [
        run_scenario(target, name, payloads, args.concurrency, args.timeout)
        for name, payloads in build_scenarios(roots, args.requests, args.top_k)
    ]

    _print_summary(results)
    if args.json is not None:
        report = {
            "port": target.port,
            "roots": roots,
            "requests": args.requests,
            "concurrency": args.concurrency,
            "with_reindex": bool(reindex_job),
            "reindex_job": reindex_job,
            "scenarios": [r.to_dict() for r in results],
        }
        args.json.write_text(
            json.dumps(report, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"report written: {args.json}", file=sys.stderr)
    return 0 if all(r.error_count == 0 for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
