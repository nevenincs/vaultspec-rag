"""Real-backend acceptance harness for the supported large code index.

The harness owns one explicitly dedicated root, builds deterministic Python
source, validates the selected support profile before loading the model, and
runs the production code-index path against the configured real vector-store
backend. It never deletes or rewrites an unmarked root.

Default acceptance command (root and report path must live under the OS temp
directory, never a bare drive-root or project-adjacent folder)::

    uv run python -m vaultspec_rag.tests.benchmarks.bench_large_index_resilience \
        --root "%TEMP%/vaultspec-rag-acceptance/large-code" --clean --local-files-only \
        --json "%TEMP%/vaultspec-rag-acceptance/large-code-report.json"

The default 83,624-file corpus produces exactly three chunks per file through
the production AST chunker, establishing the 250,872-chunk managed-service
floor with true source code.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import tempfile
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, cast

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ...indexer import CodebaseIndexer
    from ...indexer._codebase_indexer import CodeIndexPreflight
    from ...indexer._vault_prep import IndexResult

_SCHEMA_VERSION: Final = 1
_TEMPLATE_VERSION: Final = "python-three-functions-v5"
_MARKER_NAME: Final = ".large-index-resilience-corpus.json"
_DEFAULT_FILES: Final = 83_624
_DEFAULT_CHUNKS_PER_FILE: Final = 3
_DEFAULT_EXPECTED_CHUNKS: Final = 250_872
_DOCSTRING_PADDING: Final = 760
_EVIDENCE_DIR_ENV: Final = "VAULTSPEC_RAG_BENCHMARK_REPORT_DIR"
_LOG = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CorpusSpec:
    """Deterministic source-corpus dimensions."""

    files: int
    chunks_per_file: int
    template_version: str = _TEMPLATE_VERSION

    def __post_init__(self) -> None:
        if self.files <= 0:
            raise ValueError("files must be positive")
        if self.chunks_per_file <= 0:
            raise ValueError("chunks_per_file must be positive")

    @property
    def expected_chunks(self) -> int:
        return self.files * self.chunks_per_file


@dataclass(frozen=True, slots=True)
class CorpusPreparation:
    """Observable result of idempotently preparing one dedicated root."""

    created_files: int
    retained_files: int
    source_bytes: int


@dataclass(frozen=True, slots=True)
class ResourceHighWater:
    """Process and device memory observed during one production run."""

    baseline_rss_mb: float
    peak_rss_mb: float
    baseline_cuda_allocated_mb: float
    peak_cuda_allocated_mb: float
    baseline_cuda_reserved_mb: float
    peak_cuda_reserved_mb: float

    @property
    def rss_growth_mb(self) -> float:
        return max(0.0, self.peak_rss_mb - self.baseline_rss_mb)

    @property
    def cuda_allocated_growth_mb(self) -> float:
        return max(
            0.0,
            self.peak_cuda_allocated_mb - self.baseline_cuda_allocated_mb,
        )

    @property
    def cuda_reserved_growth_mb(self) -> float:
        return max(
            0.0,
            self.peak_cuda_reserved_mb - self.baseline_cuda_reserved_mb,
        )


@dataclass(frozen=True, slots=True)
class AcceptanceReport:
    """Machine-readable evidence from one production acceptance run."""

    schema_version: int
    root: str
    profile: str
    backend: str
    corpus: dict[str, object]
    result: dict[str, object]
    measurement: dict[str, int]
    resources: dict[str, float]
    wall_seconds: float


@dataclass(frozen=True, slots=True)
class MeasuredIndexRun:
    """Production result paired with its externally sampled high-water."""

    result: IndexResult
    resources: ResourceHighWater
    wall_seconds: float


class _ResourceSampler:
    """Sample real process and CUDA state at a fixed bounded cadence."""

    def __init__(self, interval_seconds: float) -> None:
        if interval_seconds <= 0.0:
            raise ValueError("sample interval must be positive")
        self._interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._baseline: tuple[float, float, float] | None = None
        self._peak: tuple[float, float, float] | None = None

    @staticmethod
    def _sample() -> tuple[float, float, float]:
        from ...memory_probe import current_cuda_mb, current_rss_mb

        allocated_mb, reserved_mb = current_cuda_mb()
        return current_rss_mb(), allocated_mb, reserved_mb

    def _observe(self) -> None:
        sample = self._sample()
        if self._baseline is None:
            self._baseline = sample
            self._peak = sample
            return
        assert self._peak is not None
        self._peak = (
            max(self._peak[0], sample[0]),
            max(self._peak[1], sample[1]),
            max(self._peak[2], sample[2]),
        )

    def _run(self) -> None:
        while not self._stop.wait(self._interval_seconds):
            self._observe()

    @staticmethod
    def _reset_native_cuda_peak() -> None:
        from ..._gpu import load_torch

        torch = load_torch()
        torch.cuda.reset_peak_memory_stats()

    @staticmethod
    def _native_cuda_peak() -> tuple[float, float]:
        from ..._gpu import load_torch

        torch = load_torch()
        mib = 1024**2
        return (
            float(torch.cuda.max_memory_allocated() / mib),
            float(torch.cuda.max_memory_reserved() / mib),
        )

    def __enter__(self) -> _ResourceSampler:
        self._observe()
        self._reset_native_cuda_peak()
        self._thread = threading.Thread(
            target=self._run,
            name="large-index-resource-sampler",
            daemon=True,
        )
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self._interval_seconds * 4.0))
            if self._thread.is_alive():
                raise RuntimeError("resource sampler did not terminate")
        self._observe()
        native_allocated, native_reserved = self._native_cuda_peak()
        assert self._peak is not None
        self._peak = (
            self._peak[0],
            max(self._peak[1], native_allocated),
            max(self._peak[2], native_reserved),
        )

    def high_water(self) -> ResourceHighWater:
        if self._baseline is None or self._peak is None:
            raise RuntimeError("resource sampler has no observations")
        return ResourceHighWater(
            baseline_rss_mb=self._baseline[0],
            peak_rss_mb=self._peak[0],
            baseline_cuda_allocated_mb=self._baseline[1],
            peak_cuda_allocated_mb=self._peak[1],
            baseline_cuda_reserved_mb=self._baseline[2],
            peak_cuda_reserved_mb=self._peak[2],
        )


def _function_source(_file_index: int, chunk_index: int) -> str:
    # Each function must remain above half the production AST character
    # budget so adjacent structural units do not merge. Whitespace supplies
    # that character boundary without turning a chunk-cardinality acceptance
    # into an accidental long-context model benchmark.
    docstring = f"{' ' * _DOCSTRING_PADDING}unit {chunk_index}"
    return (
        f'def f{chunk_index}(x):\n    """{docstring}"""\n    return x + {chunk_index}\n'
    )


def module_source(file_index: int, chunks_per_file: int) -> str:
    """Return one deterministic valid Python module."""
    functions = [
        _function_source(file_index, chunk_index)
        for chunk_index in range(chunks_per_file)
    ]
    return "\n\n\n".join(functions)


def _source_path(root: Path, file_index: int) -> Path:
    return (
        root
        / "src"
        / "acceptance_workload"
        / f"{file_index // 1000:03d}"
        / f"module_{file_index:06d}.py"
    )


def _marker_payload(spec: CorpusSpec, state: str) -> dict[str, object]:
    return {
        "schema_version": _SCHEMA_VERSION,
        "state": state,
        "files": spec.files,
        "chunks_per_file": spec.chunks_per_file,
        "expected_chunks": spec.expected_chunks,
        "template_version": spec.template_version,
    }


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(payload, stream, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def retain_benchmark_evidence(
    name: str,
    payload: dict[str, object],
    *,
    report_dir: Path | None = None,
) -> Path | None:
    """Log exact benchmark evidence and optionally retain it as atomic JSON."""
    if not name or any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789-" for character in name
    ):
        raise ValueError(
            "benchmark evidence name must use lowercase letters, digits, and hyphens"
        )
    report = {
        **payload,
        "schema_version": _SCHEMA_VERSION,
        "evidence": name,
    }
    rendered = json.dumps(report, sort_keys=True)
    _LOG.info("large-index benchmark evidence: %s", rendered)
    destination_dir = report_dir
    if destination_dir is None:
        configured_dir = os.environ.get(_EVIDENCE_DIR_ENV)
        if configured_dir:
            destination_dir = Path(configured_dir)
    if destination_dir is None:
        return None
    destination = destination_dir / (f"{name}-{os.getpid()}-{uuid.uuid4().hex}.json")
    _write_json(destination, report)
    _LOG.info("retained large-index benchmark evidence at %s", destination)
    return destination


def _load_marker(root: Path) -> dict[str, object] | None:
    marker = root / _MARKER_NAME
    if not marker.is_file():
        return None
    parsed: object = json.loads(marker.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise RuntimeError(f"invalid corpus marker at {marker}")
    return {
        str(key): value for key, value in cast("dict[object, object]", parsed).items()
    }


def _assert_owned_root(root: Path, spec: CorpusSpec) -> None:
    marker = _load_marker(root)
    if marker is None:
        if root.exists() and next(root.iterdir(), None) is not None:
            raise RuntimeError(f"refusing unmarked non-empty acceptance root: {root}")
        root.mkdir(parents=True, exist_ok=True)
        _write_json(root / _MARKER_NAME, _marker_payload(spec, "preparing"))
        return
    expected = _marker_payload(spec, str(marker.get("state", "preparing")))
    for key in ("schema_version", "files", "chunks_per_file", "template_version"):
        if marker.get(key) != expected[key]:
            raise RuntimeError(
                f"acceptance root marker {key}={marker.get(key)!r}; "
                f"requested {expected[key]!r}"
            )


def _verify_chunk_cardinality(root: Path, spec: CorpusSpec) -> None:
    from ...indexer._chunk_worker import chunk_and_hash_file

    sample_indexes = sorted({0, spec.files // 2, spec.files - 1})
    for file_index in sample_indexes:
        result = chunk_and_hash_file(_source_path(root, file_index), root)
        if len(result.chunks) != spec.chunks_per_file:
            raise RuntimeError(
                f"production chunker emitted {len(result.chunks)} chunks for "
                f"{result.rel_path}; expected {spec.chunks_per_file}"
            )


def prepare_corpus(root: Path, spec: CorpusSpec) -> CorpusPreparation:
    """Create or resume one deterministic, marker-owned source corpus."""
    resolved = root.resolve()
    _assert_owned_root(resolved, spec)
    created = 0
    retained = 0
    source_bytes = 0
    for file_index in range(spec.files):
        path = _source_path(resolved, file_index)
        source = module_source(file_index, spec.chunks_per_file)
        encoded_bytes = len(source.encode("utf-8"))
        if path.exists():
            if not path.is_file() or path.stat().st_size != encoded_bytes:
                raise RuntimeError(f"corpus source differs from its marker: {path}")
            retained += 1
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_text(source, encoding="utf-8", newline="\n")
            temporary.replace(path)
            created += 1
        source_bytes += encoded_bytes
    _verify_chunk_cardinality(resolved, spec)
    _write_json(resolved / _MARKER_NAME, _marker_payload(spec, "ready"))
    return CorpusPreparation(created, retained, source_bytes)


def measure_full_index(
    indexer: CodebaseIndexer,
    preflight: CodeIndexPreflight,
    *,
    clean: bool,
    sample_interval_seconds: float = 0.1,
) -> MeasuredIndexRun:
    """Measure one real production full-index run at a bounded cadence."""
    from ...progress import NullProgressReporter

    started = time.perf_counter()
    with _ResourceSampler(sample_interval_seconds) as sampler:
        result = indexer.full_index(
            clean=clean,
            reporter=NullProgressReporter(),
            preflight=preflight,
        )
    return MeasuredIndexRun(
        result=result,
        resources=sampler.high_water(),
        wall_seconds=time.perf_counter() - started,
    )


def validate_acceptance_admission(
    root: Path,
    spec: CorpusSpec,
) -> CodeIndexPreflight:
    """Require managed-service admission before model or mutable GPU work."""
    from ...config import get_config
    from ...jobs import validate_code_job_admission

    cfg = get_config()
    if str(cfg.index_support_profile) != "managed-service":
        raise RuntimeError(
            "large-corpus acceptance requires the managed-service support profile"
        )
    preflight = validate_code_job_admission(root.resolve())
    if preflight.scan.measurement.source_files != spec.files:
        raise RuntimeError(
            f"profile admitted {preflight.scan.measurement.source_files} source files; "
            f"expected {spec.files}"
        )
    return preflight


@dataclass(frozen=True, slots=True)
class AcceptanceRequest:
    """Inputs for one real production code-index acceptance run."""

    root: Path
    spec: CorpusSpec
    expected_chunks: int
    clean: bool
    local_files_only: bool
    sample_interval_seconds: float


def run_acceptance(request: AcceptanceRequest) -> AcceptanceReport:
    """Run profile admission and the real production code-index pipeline."""
    from ... import CodebaseIndexer, EmbeddingModel
    from ...config import get_config
    from ...store_runtime import VaultStore

    resolved = request.root.resolve()
    preparation = prepare_corpus(resolved, request.spec)
    cfg = get_config()
    preflight = validate_acceptance_admission(resolved, request.spec)

    model = EmbeddingModel(local_files_only=request.local_files_only)
    store = VaultStore(resolved)
    try:
        indexer = CodebaseIndexer(resolved, model, store)
        measured = measure_full_index(
            indexer,
            preflight,
            clean=request.clean,
            sample_interval_seconds=request.sample_interval_seconds,
        )
        result = measured.result
        resources = measured.resources
        measurement = indexer.support_measurement
        stored_chunks = store.count_code()
        if result.files != request.spec.files:
            raise RuntimeError(
                f"production index processed {result.files} files; "
                f"expected {request.spec.files}"
            )
        if stored_chunks != result.total:
            raise RuntimeError(
                f"store contains {stored_chunks} chunks; result reports {result.total}"
            )
        if measurement.generated_chunks != result.total:
            raise RuntimeError(
                "generated-chunk measurement diverged from the published collection: "
                f"{measurement.generated_chunks} != {result.total}"
            )
        if result.total < request.expected_chunks:
            raise RuntimeError(
                f"accepted corpus produced {result.total} chunks; floor is "
                f"{request.expected_chunks}"
            )
        return AcceptanceReport(
            schema_version=_SCHEMA_VERSION,
            root=str(resolved),
            profile=str(cfg.index_support_profile),
            backend="server" if cfg.qdrant_server else "local",
            corpus={
                **asdict(request.spec),
                **asdict(preparation),
                "expected_chunks": request.spec.expected_chunks,
            },
            result=asdict(result),
            measurement=asdict(measurement),
            resources={
                **asdict(resources),
                "rss_growth_mb": resources.rss_growth_mb,
                "cuda_allocated_growth_mb": resources.cuda_allocated_growth_mb,
                "cuda_reserved_growth_mb": resources.cuda_reserved_growth_mb,
            },
            wall_seconds=measured.wall_seconds,
        )
    finally:
        store.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        required=True,
        help="Dedicated, marker-owned acceptance root.",
    )
    parser.add_argument("--files", type=int, default=_DEFAULT_FILES)
    parser.add_argument(
        "--chunks-per-file",
        type=int,
        default=_DEFAULT_CHUNKS_PER_FILE,
    )
    parser.add_argument(
        "--expected-chunks",
        type=int,
        default=None,
        help="Required published chunk floor (defaults to files * chunks-per-file).",
    )
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--local-files-only", action="store_true")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--prepare-only", action="store_true")
    mode.add_argument("--admission-only", action="store_true")
    parser.add_argument("--sample-interval", type=float, default=0.1)
    parser.add_argument("--json", type=Path, default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Prepare and optionally execute the managed-service acceptance run."""
    args = _parser().parse_args(argv)
    spec = CorpusSpec(args.files, args.chunks_per_file)
    expected_chunks = args.expected_chunks or spec.expected_chunks
    if spec.files == _DEFAULT_FILES and expected_chunks < _DEFAULT_EXPECTED_CHUNKS:
        raise RuntimeError(
            f"default acceptance floor cannot be below {_DEFAULT_EXPECTED_CHUNKS}"
        )
    if args.prepare_only or args.admission_only:
        preparation = prepare_corpus(args.root, spec)
        payload: dict[str, object] = {
            "schema_version": _SCHEMA_VERSION,
            "root": str(args.root.resolve()),
            "corpus": {**asdict(spec), **asdict(preparation)},
        }
        if args.admission_only:
            from ...config import get_config

            preflight = validate_acceptance_admission(args.root, spec)
            payload.update(
                {
                    "profile": str(get_config().index_support_profile),
                    "admission": asdict(preflight.scan.measurement),
                }
            )
    else:
        report = run_acceptance(
            AcceptanceRequest(
                root=args.root,
                spec=spec,
                expected_chunks=expected_chunks,
                clean=args.clean,
                local_files_only=args.local_files_only,
                sample_interval_seconds=args.sample_interval,
            )
        )
        payload = asdict(report)
    rendered = json.dumps(payload, indent=2) + "\n"
    if args.json is not None:
        _write_json(args.json, payload)
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
