"""Bounded CPU chunking and admitted single-consumer CUDA measurements.

Run with ``python -m dev.gpu_pipeline_profile --help``. Artifacts are created
exclusively. Stack sampling and instrumented traces never contribute to sweep
throughput. Models load once, offline, on the consumer that owns all CUDA calls.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import importlib
import importlib.metadata
import json
import math
import os
import platform
import queue
import subprocess
import sys
import threading
import time
import traceback
from contextlib import contextmanager
from dataclasses import asdict
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING, Any

import psutil

from ._profile_tools import (
    PY_SPY_SHA256,
    PY_SPY_VERSION,
    PY_SPY_WHEEL_SHA256,
    PY_SPY_WHEEL_URL,
    digest,
    sample_stacks,
    trace_kernel_count,
    verify_py_spy,
    write_json,
)
from ._profile_workloads import (
    chunk_sources,
    corpus,
    corpus_manifest,
    load_sources,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from vaultspec_rag.embeddings import EmbeddingModel, EncodeBucketProgress

BATCH_SIZES = (1, 4, 8, 16, 32)
REFERENCE_TOKEN_BUDGET = 24000
SPARSE_RTOL = 1e-4
SPARSE_ATOL = 1e-5


def positive(value: str) -> int:
    number = int(value)
    if not 1 <= number <= 16384:
        raise argparse.ArgumentTypeError("Value must be between 1 and 16384")
    return number


def sparse_budgets(value: str) -> list[int]:
    try:
        budgets = [int(part) for part in value.split(",")]
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "Sparse budgets must be comma-separated integers"
        ) from exc
    if (
        not budgets
        or any(budget <= 0 for budget in budgets)
        or len(set(budgets)) != len(budgets)
    ):
        raise argparse.ArgumentTypeError(
            "Sparse budgets must be distinct positive integers"
        )
    if len(budgets) > 8 or REFERENCE_TOKEN_BUDGET not in budgets:
        raise argparse.ArgumentTypeError(
            "Provide at most eight budgets, including reference 24000"
        )
    return budgets


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("cpu", "encoder"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--py-spy", type=Path)
    parser.add_argument("--gil", action="store_true", help="Additional GIL-only pass")
    parser.add_argument("--seconds", type=int, choices=range(1, 61), default=30)
    parser.add_argument("--rounds", type=int, choices=range(1, 11), default=3)
    parser.add_argument("--warmups", type=int, choices=range(1, 6), default=2)
    parser.add_argument("--items", type=int, choices=range(1, 129), default=32)
    parser.add_argument("--chunk-size", type=positive, default=8000)
    parser.add_argument("--trace-iterations", type=int, choices=range(1, 6), default=3)
    parser.add_argument("--skip-trace", action="store_true")
    parser.add_argument(
        "--energy-seconds",
        type=int,
        choices=range(5, 61),
        help="Additional sustained combined-encoder windows per arm (caps 8 and 32)",
    )
    parser.add_argument("--sparse-budgets", type=sparse_budgets)
    parser.add_argument(
        "--sparse-budget-seconds", type=int, choices=range(5, 61), default=30
    )
    parser.add_argument("--budget-comparison-only", action="store_true")
    return parser.parse_args()


def timed_loop(call: Callable[[], object], seconds: int) -> dict[str, object]:
    deadline = time.perf_counter() + seconds
    observations = []
    while time.perf_counter() < deadline:
        started = time.perf_counter()
        result = call()
        del result
        observations.append(time.perf_counter() - started)
    return {"iterations": len(observations), "seconds": observations}


def base_manifest(
    args: argparse.Namespace,
    workloads: dict[str, list[str]],
    sources: list[tuple[str, str]],
) -> dict:
    versions = {}
    for name in (
        "vaultspec-rag",
        "torch",
        "transformers",
        "sentence-transformers",
        "tree-sitter",
        "tree-sitter-language-pack",
        "psutil",
        "nvidia-ml-py",
    ):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    source_paths = [
        Path(__file__),
        Path(__file__).with_name("_profile_tools.py"),
        Path(__file__).with_name("_profile_workloads.py"),
    ]
    source_paths.extend(
        sorted(
            path
            for path in (args.root / "src/vaultspec_rag").rglob("*.py")
            if "tests" not in path.parts
        )
    )
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=args.root,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()
    return {
        "schema": 1,
        "mode": args.mode,
        "pid": psutil.Process().pid,
        "python": sys.version,
        "versions": versions,
        "git_head": head,
        "hardware": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "logical_cpus": psutil.cpu_count(),
            "physical_cpus": psutil.cpu_count(False),
            "system_memory_bytes": psutil.virtual_memory().total,
        },
        "driver": driver_manifest(),
        "thread_environment": {
            key: os.environ.get(key)
            for key in (
                "OMP_NUM_THREADS",
                "MKL_NUM_THREADS",
                "OPENBLAS_NUM_THREADS",
                "NUMEXPR_NUM_THREADS",
                "TOKENIZERS_PARALLELISM",
                "RAYON_NUM_THREADS",
            )
        },
        "source_sha256": {
            str(path.relative_to(args.root)): digest(path) for path in source_paths
        },
        "corpus": corpus_manifest(args.root, workloads, sources),
        "corpus_chunk_sizes": sorted({args.chunk_size, min(512, args.chunk_size)}),
        "configuration": {
            key: str(value) if isinstance(value, Path) else value
            for key, value in vars(args).items()
        },
        "native_profiler": {
            "version": PY_SPY_VERSION,
            "binary_sha256": PY_SPY_SHA256,
            "wheel_sha256": PY_SPY_WHEEL_SHA256,
            "wheel_url": PY_SPY_WHEEL_URL,
        },
        "limitations": [
            "NVML is device-wide, one-second sampling; short peaks may be missed",
            "WDDM process memory may be unavailable",
            "GIL-only samples omit extensions that release the GIL",
            "Nonblocking sampling can miss frames while interpreter state changes",
        ],
    }


def cpu_run(args: argparse.Namespace, sources: list[tuple[str, str]]) -> dict:
    def chunk() -> object:
        return chunk_sources(sources, args.chunk_size)

    for _ in range(args.warmups):
        chunk()
    sweep = []
    for round_index in range(args.rounds):
        start = time.perf_counter()
        chunks = chunk_sources(sources, args.chunk_size)
        sweep.append(
            {
                "round": round_index,
                "seconds": time.perf_counter() - start,
                "chunks": len(chunks),
                "rss": psutil.Process().memory_info().rss,
                "output_sha256": hashlib.sha256(
                    json.dumps(chunks, ensure_ascii=False).encode()
                ).hexdigest(),
            }
        )
    with sample_stacks(args.py_spy, args.output / "cpu.speedscope.json", args.seconds):
        sampling = timed_loop(chunk, args.seconds)
    if args.gil:
        with sample_stacks(
            args.py_spy, args.output / "cpu-gil.speedscope.json", args.seconds, gil=True
        ):
            timed_loop(chunk, args.seconds)
    return {"unprofiled": sweep, "sampling_workload": sampling}


class DeviceSampler:
    """Optional NVML sampling, with no CUDA context or inference operations."""

    def __init__(self) -> None:
        self.stop = threading.Event()
        self.samples: list[dict[str, object]] = []
        self.error: str | None = None
        self.power_error: str | None = None
        self.thread = threading.Thread(
            target=self.run, name="nvml-sampler", daemon=True
        )

    def run(self) -> None:
        try:
            nvml = importlib.import_module("pynvml")
        except ImportError:
            self.error = "pynvml is not installed"
            return
        initialized = False
        try:
            nvml.nvmlInit()
            initialized = True
            handle = nvml.nvmlDeviceGetHandleByIndex(0)
            while not self.stop.is_set():
                memory = nvml.nvmlDeviceGetMemoryInfo(handle)
                utilization = nvml.nvmlDeviceGetUtilizationRates(handle)
                try:
                    power = nvml.nvmlDeviceGetPowerUsage(handle)
                except Exception as exc:
                    power = None
                    self.power_error = f"{type(exc).__name__}: {exc}"
                self.samples.append(
                    {
                        "monotonic": time.perf_counter(),
                        "device_used_bytes": memory.used,
                        "device_total_bytes": memory.total,
                        "gpu_utilization_percent": utilization.gpu,
                        "memory_utilization_percent": utilization.memory,
                        "power_milliwatts": power,
                    }
                )
                self.stop.wait(1)
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"
        finally:
            if initialized:
                nvml.nvmlShutdown()


def memory_snapshot(torch: Any) -> dict[str, int]:
    return {
        "allocated": torch.cuda.memory_allocated(),
        "reserved": torch.cuda.memory_reserved(),
        "rss": psutil.Process().memory_info().rss,
    }


def bucket_observer(events: list[dict]) -> Callable[[str, EncodeBucketProgress], None]:
    def observe(stage: str, progress: EncodeBucketProgress) -> None:
        events.append({"stage": stage, **asdict(progress)})

    return observe


def encode_call(
    model: EmbeddingModel, texts: list[str], size: int, kind: str, events: list[dict]
) -> None:
    observe = bucket_observer(events)
    if kind in ("dense", "combined"):
        dense = model.encode_documents_on_device(
            texts, batch_size=size, on_bucket=observe
        )
        dense.cpu()
        del dense
    if kind in ("sparse", "combined"):
        sparse = model.encode_documents_sparse(
            texts, batch_size=size, on_bucket=observe
        )
        del sparse


def sweep(
    model: EmbeddingModel,
    torch: Any,
    args: argparse.Namespace,
    workloads: dict[str, list[str]],
) -> list[dict]:
    observations = []
    for name, texts in workloads.items():
        for kind in ("dense", "sparse", "combined"):
            for size in BATCH_SIZES:
                for _ in range(args.warmups):
                    encode_call(model, texts, size, kind, [])
            for round_index in range(args.rounds):
                sizes = BATCH_SIZES if round_index % 2 == 0 else BATCH_SIZES[::-1]
                for size in sizes:
                    torch.cuda.synchronize()
                    baseline = memory_snapshot(torch)
                    ceilings_before = ceiling_state(model)
                    torch.cuda.reset_peak_memory_stats()
                    events: list[dict] = []
                    start = time.perf_counter()
                    encode_call(model, texts, size, kind, events)
                    torch.cuda.synchronize()
                    elapsed = time.perf_counter() - start
                    observations.append(
                        {
                            "workload": name,
                            "kind": kind,
                            "batch_size": size,
                            "round": round_index,
                            "seconds": elapsed,
                            "items_per_second": len(texts) / elapsed,
                            "baseline": baseline,
                            "settled": memory_snapshot(torch),
                            "peak_allocated": torch.cuda.max_memory_allocated(),
                            "peak_reserved": torch.cuda.max_memory_reserved(),
                            "buckets": events,
                            "ceilings_before": ceilings_before,
                            "ceilings_after": ceiling_state(model),
                            "bucket_attempts": sum(
                                e["stage"] == "before" for e in events
                            ),
                            "oom_count": sum(oom_counts(events).values()),
                            "oom_count_by_encoder": oom_counts(events),
                        }
                    )
    return observations


def oom_counts(events: list[dict]) -> dict[str, int]:
    return {
        kind: max(
            (event["oom_count"] for event in events if event["kind"] == kind), default=0
        )
        for kind in ("dense", "sparse")
    }


def energy_summary(
    samples: list[dict[str, object]], start: float, end: float, items: int
) -> dict:
    summary = {
        "scope": "device-wide NVML power, including other device workloads",
        "sample_count": 0,
        "sampled_span_seconds": 0.0,
        "window_seconds": end - start,
        "coverage_fraction": 0.0,
        "sampling_complete": False,
        "device_wide_joules": None,
        "device_wide_joules_per_item_estimate": None,
        "reason": None,
    }
    if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
        summary["reason"] = "Invalid window times"
        return summary
    points: list[tuple[float, float]] = []
    previous = -1.0
    for sample in samples:
        stamp = sample.get("monotonic")
        if (
            not isinstance(stamp, (int, float))
            or not math.isfinite(stamp)
            or stamp < 0
            or stamp <= previous
        ):
            summary["reason"] = "Negative, invalid or nonmonotonic sample times"
            return summary
        previous = stamp
        power = sample.get("power_milliwatts")
        if not start <= stamp <= end or power is None:
            continue
        if not isinstance(power, (int, float)) or not math.isfinite(power) or power < 0:
            summary["reason"] = "Invalid power sample"
            return summary
        points.append((stamp, power / 1000))
    summary["sample_count"] = len(points)
    if len(points) < 2:
        summary["reason"] = "Fewer than two valid in-window power samples"
        return summary
    span = points[-1][0] - points[0][0]
    summary["sampled_span_seconds"] = span
    summary["coverage_fraction"] = span / (end - start)
    intervals = list(pairwise(points))
    if any(right[0] - left[0] > 2.5 for left, right in intervals):
        summary["reason"] = "Power samples have a gap above 2.5 seconds"
        return summary
    joules = sum(
        (right[0] - left[0]) * (left[1] + right[1]) / 2 for left, right in intervals
    )
    summary["device_wide_joules"] = joules
    summary["sampling_complete"] = summary["coverage_fraction"] >= 0.9
    if summary["sampling_complete"] and items > 0:
        summary["device_wide_joules_per_item_estimate"] = (
            joules / span / (items / (end - start))
        )
    else:
        summary["reason"] = "Incomplete sampling coverage; per-item estimate withheld"
    return summary


def energy_windows(
    model: EmbeddingModel,
    torch: Any,
    args: argparse.Namespace,
    workloads: dict[str, list[str]],
    sampler: DeviceSampler,
) -> list[dict]:
    windows = []
    for name, texts in workloads.items():
        for round_index in range(args.rounds):
            order = (8, 32) if round_index % 2 == 0 else (32, 8)
            for size in order:
                row = sustained_window(
                    model,
                    torch,
                    texts,
                    sampler,
                    {"size": size, "seconds": args.energy_seconds},
                )
                windows.append(
                    {
                        "workload": name,
                        "round": round_index,
                        "arm_order": list(order),
                        **row,
                    }
                )
    return windows


def sustained_window(
    model: EmbeddingModel,
    torch: Any,
    texts: list[str],
    sampler: DeviceSampler,
    arm: dict,
) -> dict:
    torch.cuda.synchronize()
    baseline = memory_snapshot(torch)
    ceilings_before = ceiling_state(model)
    torch.cuda.reset_peak_memory_stats()
    attempts: dict[str, dict[int, int]] = {"dense": {}, "sparse": {}}
    ooms = {"dense": 0, "sparse": 0}
    iterations = 0
    start = time.perf_counter()
    while time.perf_counter() < start + arm["seconds"]:
        events: list[dict] = []
        encode_call(model, texts, arm["size"], "combined", events)
        torch.cuda.synchronize()
        iterations += 1
        for kind, count in oom_counts(events).items():
            ooms[kind] += count
        for event in events:
            if event["stage"] == "before":
                histogram = attempts[event["kind"]]
                actual_size = event["bucket_items"]
                histogram[actual_size] = histogram.get(actual_size, 0) + 1
    end = time.perf_counter()
    items = iterations * len(texts)
    return {
        "requested_batch_size": arm["size"],
        "kind": "dense_then_sparse",
        "start_monotonic": start,
        "end_monotonic": end,
        "seconds": end - start,
        "iterations": iterations,
        "input_items": items,
        "items_per_second": items / (end - start),
        "baseline": baseline,
        "settled": memory_snapshot(torch),
        "peak_allocated": torch.cuda.max_memory_allocated(),
        "peak_reserved": torch.cuda.max_memory_reserved(),
        "ceilings_before": ceilings_before,
        "ceilings_after": ceiling_state(model),
        "bucket_attempt_item_histograms": attempts,
        "oom_count_by_encoder": ooms,
        "energy": energy_summary(sampler.samples.copy(), start, end, items),
    }


@contextmanager
def sparse_budget_arm(model: Any, budget: int) -> Iterator[None]:
    from vaultspec_rag.embeddings import EncodeBatchCeiling

    original_budget = model._sparse_encode_token_budget
    original_ceiling = model._sparse_batch_ceiling
    try:
        model._sparse_encode_token_budget = budget
        model._sparse_batch_ceiling = EncodeBatchCeiling()
        yield
    finally:
        model._sparse_encode_token_budget = original_budget
        model._sparse_batch_ceiling = original_ceiling


def sparse_budget_windows(
    model: Any,
    torch: Any,
    args: argparse.Namespace,
    workloads: dict[str, list[str]],
    sampler: DeviceSampler,
) -> list[dict]:
    if model._encode_token_budget != REFERENCE_TOKEN_BUDGET:
        raise ValueError(
            "Sparse comparison requires unchanged dense token budget 24000"
        )
    windows = []
    artifacts = args.output / "sparse-budget-window-rows"
    artifacts.mkdir()
    for name, texts in workloads.items():
        for round_index in range(args.rounds):
            order = (
                args.sparse_budgets
                if round_index % 2 == 0
                else args.sparse_budgets[::-1]
            )
            for budget in order:
                with sparse_budget_arm(model, budget):
                    warm_events: list[dict] = []
                    for _ in range(args.warmups):
                        encode_call(model, texts, 32, "combined", warm_events)
                    row = sustained_window(
                        model,
                        torch,
                        texts,
                        sampler,
                        {"size": 32, "seconds": args.sparse_budget_seconds},
                    )
                    row = {
                        "workload": name,
                        "round": round_index,
                        "sparse_budget_order": list(order),
                        "dense_token_budget": model._encode_token_budget,
                        "sparse_token_budget": model._sparse_encode_token_budget,
                        "warmup_buckets": warm_events,
                        **row,
                    }
                    windows.append(row)
                    write_json(artifacts / f"{len(windows):03d}.json", row)
    return windows


def ceiling_state(model: Any) -> dict:
    return {
        name: {
            "token_ceiling": ceiling._ceiling,
            "successes_at_ceiling": ceiling._successes_at_ceiling,
        }
        for name, ceiling in (
            ("dense", model._dense_batch_ceiling),
            ("sparse", model._sparse_batch_ceiling),
        )
    }


@contextmanager
def forward_token_capture(
    model: Any, current: dict, observations: list[dict]
) -> Iterator[None]:
    def capture(kind: str) -> Callable:
        def hook(_module: object, positional: tuple, keywords: dict) -> None:
            mask = keywords.get("attention_mask")
            if mask is None and len(positional) > 1:
                mask = positional[1]
            if mask is None:
                raise RuntimeError("Forward telemetry did not receive attention_mask")
            observations.append(
                {
                    **current,
                    "kind": kind,
                    "tokens": mask.sum(dim=1).cpu().tolist(),
                    "padded_length": mask.shape[1],
                    "items": mask.shape[0],
                }
            )

        return hook

    dense = model._dense_model[0].auto_model
    sparse = model._require_sparse_model()._model
    handles = [
        dense.register_forward_pre_hook(capture("dense"), with_kwargs=True),
        sparse.register_forward_pre_hook(capture("sparse"), with_kwargs=True),
    ]
    try:
        yield
    finally:
        for handle in handles:
            handle.remove()


def bucket_token_telemetry(model: Any, workloads: dict[str, list[str]]) -> list[dict]:
    observations: list[dict] = []
    current: dict = {}
    with forward_token_capture(model, current, observations):
        for name, texts in workloads.items():
            for size in (8, 32):
                current.update(workload=name, batch_size=size)
                encode_call(model, texts, size, "combined", [])
    return observations


def compare_sparse_vectors(reference: Any, candidate: Any) -> dict:
    import numpy as np

    coordinates_equal = reference.indices == candidate.indices
    left, right = np.asarray(reference.values), np.asarray(candidate.values)
    reference_valid = bool(np.isfinite(left).all() and (left >= 0).all())
    candidate_valid = bool(np.isfinite(right).all() and (right >= 0).all())
    aligned = coordinates_equal and left.shape == right.shape
    return {
        "coordinates_equal": coordinates_equal,
        "reference_nonzero": len(reference.indices),
        "candidate_nonzero": len(candidate.indices),
        "reference_weights_valid": reference_valid,
        "candidate_weights_valid": candidate_valid,
        "reference_sha256": hashlib.sha256(
            json.dumps([reference.indices, reference.values]).encode()
        ).hexdigest(),
        "candidate_sha256": hashlib.sha256(
            json.dumps([candidate.indices, candidate.values]).encode()
        ).hexdigest(),
        "scores_close": bool(
            aligned
            and reference_valid
            and candidate_valid
            and np.allclose(left, right, rtol=SPARSE_RTOL, atol=SPARSE_ATOL)
        ),
        "maximum_absolute_score_error": float(np.max(np.abs(left - right)))
        if aligned and reference_valid and candidate_valid and left.size
        else None,
    }


def sparse_dot(query: Any, document: Any) -> float:
    weights = dict(zip(query.indices, query.values, strict=True))
    return sum(
        weights.get(index, 0.0) * value
        for index, value in zip(document.indices, document.values, strict=True)
    )


def compare_sparse_dot_scores(reference: list[float], candidate: list[float]) -> dict:
    import numpy as np

    reference_finite = bool(np.isfinite(reference).all())
    candidate_finite = bool(np.isfinite(candidate).all())
    return {
        "reference_finite": reference_finite,
        "candidate_finite": candidate_finite,
        "scores_close": bool(
            reference_finite
            and candidate_finite
            and np.allclose(reference, candidate, rtol=SPARSE_RTOL, atol=SPARSE_ATOL)
        ),
        "reference_scores": [
            value if math.isfinite(value) else None for value in reference
        ],
        "candidate_scores": [
            value if math.isfinite(value) else None for value in candidate
        ],
    }


def sparse_output_parity(
    model: Any, args: argparse.Namespace, workloads: dict[str, list[str]]
) -> list[dict]:
    rows = []
    observations: list[dict] = []
    current: dict = {}
    with forward_token_capture(model, current, observations):
        for name, texts in workloads.items():
            current.update(
                workload=name,
                sparse_token_budget=REFERENCE_TOKEN_BUDGET,
                path="document",
            )
            with sparse_budget_arm(model, REFERENCE_TOKEN_BUDGET):
                dense = model.encode_documents_on_device(texts, batch_size=32)
                dense.cpu()
                del dense
                reference_events: list[dict] = []
                reference_docs = model.encode_documents_sparse(
                    texts, batch_size=32, on_bucket=bucket_observer(reference_events)
                )
                current["path"] = "query"
                reference_query = model.encode_query_sparse(texts[0])
            for budget in args.sparse_budgets:
                current.update(sparse_token_budget=budget, path="document")
                with sparse_budget_arm(model, budget):
                    candidate_events: list[dict] = []
                    documents = model.encode_documents_sparse(
                        texts,
                        batch_size=32,
                        on_bucket=bucket_observer(candidate_events),
                    )
                    current["path"] = "query"
                    query = model.encode_query_sparse(texts[0])
                vector_rows = [
                    compare_sparse_vectors(left, right)
                    for left, right in zip(reference_docs, documents, strict=True)
                ]
                query_row = compare_sparse_vectors(reference_query, query)
                reference_scores = [
                    sparse_dot(reference_query, doc) for doc in reference_docs
                ]
                candidate_scores = [sparse_dot(query, doc) for doc in documents]
                dot_scores = compare_sparse_dot_scores(
                    reference_scores, candidate_scores
                )
                score_close = dot_scores["scores_close"]
                rows.append(
                    {
                        "workload": name,
                        "reference_sparse_token_budget": REFERENCE_TOKEN_BUDGET,
                        "candidate_sparse_token_budget": budget,
                        "batch_size": 32,
                        "reference_document_buckets": reference_events,
                        "candidate_document_buckets": candidate_events,
                        "dense_token_budget": model._encode_token_budget,
                        "relative_tolerance": SPARSE_RTOL,
                        "absolute_tolerance": SPARSE_ATOL,
                        "query": query_row,
                        "documents": vector_rows,
                        "reference_query_document_dot_scores": dot_scores[
                            "reference_scores"
                        ],
                        "candidate_query_document_dot_scores": dot_scores[
                            "candidate_scores"
                        ],
                        "reference_query_document_scores_finite": dot_scores[
                            "reference_finite"
                        ],
                        "candidate_query_document_scores_finite": dot_scores[
                            "candidate_finite"
                        ],
                        "query_document_scores_close": score_close,
                        "pass": score_close
                        and query_row["scores_close"]
                        and all(row["scores_close"] for row in vector_rows),
                    }
                )
                write_json(
                    args.output / f"sparse-parity-{name}-{budget}.json", rows[-1]
                )
    write_json(args.output / "sparse-budget-forward-tokens.json", observations)
    return rows


def budget_comparison(
    model: Any,
    torch: Any,
    args: argparse.Namespace,
    workloads: dict[str, list[str]],
    sampler: DeviceSampler,
) -> dict:
    parity = sparse_output_parity(model, args, workloads)
    write_json(args.output / "sparse-budget-parity.json", parity)
    if not all(row["pass"] for row in parity):
        raise RuntimeError(
            "Sparse budget output parity failed; inspect parity artifacts"
        )
    windows = sparse_budget_windows(model, torch, args, workloads, sampler)
    write_json(args.output / "sparse-budget-windows.json", windows)
    return {"sparse_budget_parity": parity, "sparse_budget_windows": windows}


def token_telemetry(model: Any, workloads: dict[str, list[str]]) -> dict:
    telemetry = {}
    cap = model._default_max_embed_chars()
    for name, texts in workloads.items():
        truncated = [text[:cap] for text in texts]
        dense = model._dense_model.tokenize(truncated)
        sparse = model._require_sparse_model().prepare(truncated, kind="document")
        telemetry[name] = {
            "dense": {
                "tokens": dense["attention_mask"].sum(dim=1).tolist(),
                "padded_length": dense["input_ids"].shape[1],
            },
            "sparse": {
                "tokens": sparse[1].sum(dim=1).tolist(),
                "padded_length": sparse[0].shape[1],
            },
        }
    return {
        "scope": "separate full-corpus tokenization, not timed bucket padding",
        "max_embed_chars": cap,
        "workloads": telemetry,
    }


def model_manifest(model: Any) -> dict:
    from vaultspec_rag._sparse_profile import SPARSE_MODEL_ID, sparse_model_revision
    from vaultspec_rag.config._settings import get_config

    dense = model._dense_model
    transformer = dense[0].auto_model
    sparse = model._require_sparse_model()._model
    cfg = get_config()
    torch = model._accelerator.torch
    properties = torch.cuda.get_device_properties(0)
    return {
        "device": model._accelerator.name,
        "backend": model._accelerator.backend,
        "cuda_runtime": torch.version.cuda,
        "cudnn_version": torch.backends.cudnn.version(),
        "device_total_memory_bytes": properties.total_memory,
        "device_capability": [properties.major, properties.minor],
        "torch_cpu_threads": torch.get_num_threads(),
        "torch_interop_threads": torch.get_num_interop_threads(),
        "driver": driver_manifest(),
        "dense": {
            "model": cfg.embedding_model,
            "revision": getattr(transformer.config, "_commit_hash", None),
            "dtype": str(transformer.dtype),
            "attention": getattr(transformer.config, "_attn_implementation", None),
            "max_sequence_length": dense.max_seq_length,
        },
        "sparse": {
            "model": SPARSE_MODEL_ID,
            "revision": sparse_model_revision(SPARSE_MODEL_ID),
            "dtype": str(sparse.dtype),
            "attention": getattr(sparse.config, "_attn_implementation", None),
        },
        "encode_batch_size": cfg.embedding_encode_batch_size,
        "dense_token_budget": model._encode_token_budget,
        "sparse_token_budget": model._sparse_encode_token_budget,
    }


def driver_manifest() -> dict:
    try:
        nvml = importlib.import_module("pynvml")
    except ImportError:
        return {"version": None, "reason": "pynvml is not installed"}
    initialized = False
    try:
        nvml.nvmlInit()
        initialized = True
        version = nvml.nvmlSystemGetDriverVersion()
        return {"version": version.decode() if isinstance(version, bytes) else version}
    except Exception as exc:
        return {"version": None, "reason": f"{type(exc).__name__}: {exc}"}
    finally:
        if initialized:
            nvml.nvmlShutdown()


def cuda_trace(
    model: EmbeddingModel, torch: Any, args: argparse.Namespace, texts: list[str]
) -> dict:
    trace = args.output / "cuda-trace.json"
    with torch.profiler.profile(
        activities=[
            torch.profiler.ProfilerActivity.CPU,
            torch.profiler.ProfilerActivity.CUDA,
        ],
        record_shapes=True,
        profile_memory=True,
    ) as profiler:
        for _ in range(args.trace_iterations):
            encode_call(model, texts, 32, "combined", [])
            torch.cuda.synchronize()
            profiler.step()
    profiler.export_chrome_trace(str(trace))
    with (args.output / "operators.txt").open("x", encoding="utf-8") as stream:
        stream.write(
            profiler.key_averages(group_by_input_shape=True).table(
                sort_by="self_cuda_time_total", row_limit=50
            )
        )
    kernels = trace_kernel_count(trace)
    return {
        "iterations": args.trace_iterations,
        "actual_cuda_kernel_events": kernels,
        "cuda_device_attribution_available": kernels > 0,
    }


def encoder_work(args: argparse.Namespace, workloads: dict[str, list[str]]) -> dict:
    from vaultspec_rag.embeddings import EmbeddingModel

    model = EmbeddingModel(local_files_only=True)
    torch = model._accelerator.torch
    if model._accelerator.backend != "cuda":
        raise RuntimeError("This profiler requires CUDA")
    result = {
        "model": model_manifest(model),
        "tokens": token_telemetry(model, workloads),
    }
    write_json(args.output / "model-manifest.json", result)
    sampler = DeviceSampler()
    sampler.thread.start()
    try:
        if not args.budget_comparison_only:
            result["unprofiled"] = sweep(model, torch, args, workloads)
            write_json(args.output / "sweep.json", result["unprofiled"])
        if args.sparse_budgets is not None:
            result.update(budget_comparison(model, torch, args, workloads, sampler))
        if args.energy_seconds is not None:
            result["energy_windows"] = energy_windows(
                model, torch, args, workloads, sampler
            )
            write_json(args.output / "energy-windows.json", result["energy_windows"])
        if not args.budget_comparison_only:
            write_json(
                args.output / "bucket-tokens.json",
                {
                    "scope": "separate observed forwards; excluded from throughput",
                    "buckets": bucket_token_telemetry(model, workloads),
                },
            )
        texts = workloads["mixed"]

        def warm_call() -> None:
            encode_call(model, texts, 32, "combined", [])
            torch.cuda.synchronize()

        with sample_stacks(
            args.py_spy, args.output / "encoder.speedscope.json", args.seconds
        ):
            result["sampling_workload"] = timed_loop(warm_call, args.seconds)
        if args.gil:
            with sample_stacks(
                args.py_spy,
                args.output / "encoder-gil.speedscope.json",
                args.seconds,
                gil=True,
            ):
                timed_loop(warm_call, args.seconds)
        if not args.skip_trace:
            result["trace"] = cuda_trace(model, torch, args, texts)
    finally:
        sampler.stop.set()
        sampler.thread.join(timeout=5)
        write_json(
            args.output / "nvml.json",
            {
                "scope": "device-wide, one-second samples",
                "error": sampler.error,
                "power_error": sampler.power_error,
                "samples": sampler.samples,
                "shutdown_complete": not sampler.thread.is_alive(),
            },
        )
        if sampler.thread.is_alive():
            raise RuntimeError("NVML sampler did not stop within five seconds")
    return result


def encoder_run(args: argparse.Namespace, workloads: dict[str, list[str]]) -> dict:
    from vaultspec_rag._gpu import load_accelerator

    accelerator = load_accelerator()
    try:
        return encoder_work(args, workloads)
    except BaseException as exc:
        # Failed inference tracebacks can retain model tensors after work unwinds.
        pending = [exc]
        seen: set[int] = set()
        while pending:
            failure = pending.pop()
            if id(failure) in seen:
                continue
            seen.add(id(failure))
            traceback.clear_frames(failure.__traceback__)
            pending.extend(
                error
                for error in (failure.__cause__, failure.__context__)
                if error is not None
            )
        raise
    finally:
        # This is the sole cache release, after model locals and closures unwind.
        gc.collect()
        accelerator.torch.cuda.synchronize()
        accelerator.release_cache()
        accelerator.torch.cuda.synchronize()
        write_json(args.output / "teardown.json", memory_snapshot(accelerator.torch))


def dedicated_consumer(work: Callable[[], dict]) -> dict:
    completed: queue.Queue[dict | BaseException] = queue.Queue(maxsize=1)

    def consume() -> None:
        try:
            completed.put(work())
        except BaseException as exc:
            completed.put(exc)

    consumer = threading.Thread(
        target=consume, name="gpu-profile-consumer", daemon=True
    )
    consumer.start()
    consumer.join(timeout=1800)
    if consumer.is_alive():
        # Exit the borrower process; never resume service while CUDA remains active.
        os._exit(124)
    outcome = completed.get_nowait()
    if isinstance(outcome, BaseException):
        raise outcome
    return outcome


def validate_options(args: argparse.Namespace) -> None:
    if args.budget_comparison_only and args.sparse_budgets is None:
        raise ValueError("--budget-comparison-only requires --sparse-budgets")
    if args.sparse_budgets is not None and args.mode != "encoder":
        raise ValueError("--sparse-budgets requires encoder mode")
    duration = (args.energy_seconds or 0) * args.rounds * 8
    if args.sparse_budgets is not None:
        duration += (
            args.sparse_budget_seconds * args.rounds * 4 * len(args.sparse_budgets)
        )
    if duration > 1200:
        raise ValueError(
            "Sustained windows exceed 1200 seconds; reduce rounds or duration"
        )
    if args.energy_seconds is not None and args.mode != "encoder":
        raise ValueError("--energy-seconds requires encoder mode")
    if args.gil and args.py_spy is None:
        raise ValueError("--gil requires --py-spy")


def main() -> None:
    args = arguments()
    validate_options(args)
    if args.py_spy is not None:
        verify_py_spy(args.py_spy)
    args.output.mkdir(parents=True, exist_ok=False)
    sources = load_sources(args.root)
    chunks = chunk_sources(sources, args.chunk_size)
    if args.chunk_size > 512:
        chunks.extend(chunk_sources(sources, 512))
    workloads = corpus(chunks, args.items)
    manifest = base_manifest(args, workloads, sources)
    write_json(args.output / "manifest.json", manifest)
    result: dict = {}
    if args.mode == "cpu":
        result = cpu_run(args, sources)
    else:
        from vaultspec_rag.cli._gpu_lease import run_with_borrowed_gpu

        def borrowed_work() -> None:
            result.update(dedicated_consumer(lambda: encoder_run(args, workloads)))

        run_with_borrowed_gpu(requested_port=None, work=borrowed_work)
    changed = [
        name
        for name, original in manifest["source_sha256"].items()
        if digest(args.root / name) != original
    ]
    changed.extend(
        name
        for name, original in manifest["corpus"]["files"].items()
        if digest(args.root / name) != original and name not in changed
    )
    result["source_stability"] = {"stable": not changed, "changed_files": changed}
    write_json(args.output / "results.json", result)
    if changed:
        raise RuntimeError(
            "Source files changed during measurement; evidence is invalid"
        )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "mode": args.mode,
                "observations": len(result.get("unprofiled", [])),
                "trace": result.get("trace"),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
