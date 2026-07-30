"""Named production acceptance harness for bounded document indexing.

The harness owns a marker-protected root and creates both directly decoded and
out-of-process extracted inputs.  Ownership comes only from explicit route
configuration; directory names have no routing meaning.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, cast

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ... import EmbeddingModel
    from ...indexer import DocumentIndexer
    from ...indexer._content_policy import RootContentPolicy
    from ...indexer._vault_prep import IndexResult
    from ...job_control import RunControlToken
    from ...store_runtime import VaultStore

_SCHEMA_VERSION: Final = 1
_MARKER_NAME: Final = ".document-index-resilience-workload.json"
_EXTRACTOR_NAME: Final = "document_workload_extractor.py"


@dataclass(frozen=True, slots=True)
class DocumentWorkloadSpec:
    """Deterministic dimensions for one generic document workload."""

    raw_files: int = 4
    extracted_files: int = 4
    units_per_extracted_file: int = 3
    words_per_unit: int = 160

    def __post_init__(self) -> None:
        for name in (
            "raw_files",
            "extracted_files",
            "units_per_extracted_file",
            "words_per_unit",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")

    @property
    def source_files(self) -> int:
        return self.raw_files + self.extracted_files


@dataclass(frozen=True, slots=True)
class PreparedDocumentWorkload:
    """Observable preparation result for a marker-owned workload root."""

    created_files: int
    retained_files: int
    source_files: int
    source_bytes: int


@dataclass(frozen=True, slots=True)
class DocumentWorkloadMeasurement:
    """All independently bounded document dimensions observed in production."""

    source_files: int
    source_bytes: int
    extracted_bytes: int
    generated_chunks: int
    weighted_bytes: int
    queue_bytes: int
    rss_bytes: int
    cuda_bytes: int


@dataclass(frozen=True, slots=True)
class DocumentAcceptanceReport:
    """Machine-readable completion and storage-confirmed resume evidence."""

    schema_version: int
    root: str
    profile: str
    backend: str
    prepared: dict[str, int]
    measurement: dict[str, int]
    result: dict[str, object]
    interrupted_generation: str
    confirmed_before_resume: int
    confirmed_after_resume: int


class _RuntimeSampler:
    """Observe process and CUDA high-water bytes at a bounded cadence."""

    def __init__(self, interval_seconds: float = 0.05) -> None:
        if interval_seconds <= 0:
            raise ValueError("sample interval must be positive")
        self._interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.rss_bytes = 0
        self.cuda_bytes = 0

    def _observe(self) -> None:
        from ...memory_probe import current_cuda_mib, current_rss_mib

        _allocated_mib, reserved_mib = current_cuda_mib()
        self.rss_bytes = max(self.rss_bytes, int(current_rss_mib() * 1024**2))
        self.cuda_bytes = max(self.cuda_bytes, int(reserved_mib * 1024**2))

    def _run(self) -> None:
        while not self._stop.wait(self._interval_seconds):
            self._observe()

    def __enter__(self) -> _RuntimeSampler:
        self._observe()
        self._thread = threading.Thread(
            target=self._run,
            name="document-workload-resource-sampler",
            daemon=True,
        )
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self._interval_seconds * 4))
            if self._thread.is_alive():
                raise RuntimeError("document workload sampler did not terminate")
        self._observe()


def _policy() -> RootContentPolicy:
    from ...indexer._content_policy import (
        ContentKind,
        ContentRoute,
        RootContentPolicy,
        SourceProfileVersion,
    )

    return RootContentPolicy(
        SourceProfileVersion.CONVENTIONAL_V1,
        (ContentRoute("inputs/raw/*.txt", ContentKind.DOCUMENT),),
    )


def _marker_payload(spec: DocumentWorkloadSpec) -> dict[str, object]:
    return {"schema_version": _SCHEMA_VERSION, **asdict(spec)}


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _claim_root(root: Path, spec: DocumentWorkloadSpec) -> None:
    expected = _marker_payload(spec)
    marker = root / _MARKER_NAME
    if marker.is_file():
        actual = json.loads(marker.read_text(encoding="utf-8"))
        if actual != expected:
            raise RuntimeError("document workload marker does not match the request")
        return
    if root.exists() and next(root.iterdir(), None) is not None:
        raise RuntimeError(f"refusing unmarked non-empty workload root: {root}")
    root.mkdir(parents=True, exist_ok=True)
    _write_json(marker, expected)


def _extractor_source() -> str:
    return """\
import hashlib
import json
import os
from pathlib import Path
import sys

source = Path(sys.argv[1])
raw = source.read_bytes()
invocation = json.loads(os.environ["VAULTSPEC_PREPROCESS_INVOCATION"])
units = int(invocation["options"]["units"])
words = int(invocation["options"]["words"])
token = hashlib.blake2b(raw, digest_size=8).hexdigest()
payload = {
    "schema_version": 1,
    "preprocessor_id": "document-workload",
    "preprocessor_version": invocation["extractor_version"],
    "source_path": invocation["source_paths"][0],
    "metadata": {"fixture": "generic-binary"},
    "units": [
        {
            "title": f"Unit {ordinal}",
            "section": "Acceptance",
            "anchor": f"unit={ordinal}",
            "locator": {"kind": "line", "value": ordinal + 1},
            "text": " ".join(
                f"document_{token}_{ordinal}_{word}" for word in range(words)
            ),
        }
        for ordinal in range(units)
    ],
}
print(json.dumps(payload, separators=(",", ":")))
"""


def _configuration(root: Path, spec: DocumentWorkloadSpec) -> str:
    executable = str(Path(sys.executable).resolve()).replace("\\", "/")
    extractor = str((root / _EXTRACTOR_NAME).resolve()).replace("\\", "/")
    return (
        "version = 2\n\n"
        "[[rule]]\n"
        'pattern = "inputs/extracted/*.blob"\n'
        f'command = \'"{executable}" "{extractor}" {{path}}\'\n'
        'target = "document"\n'
        'extractor_version = "1"\n'
        'on_error = "fail"\n'
        "[rule.options]\n"
        f"units = {spec.units_per_extracted_file}\n"
        f"words = {spec.words_per_unit}\n"
    )


def _raw_text(file_index: int, words: int) -> str:
    return " ".join(f"raw_document_{file_index}_{word}" for word in range(words))


def _write_if_absent(path: Path, payload: bytes) -> bool:
    if path.is_file():
        if path.read_bytes() != payload:
            raise RuntimeError(f"workload input differs from its marker: {path}")
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)
    return True


def prepare_document_workload(
    root: Path,
    spec: DocumentWorkloadSpec,
) -> PreparedDocumentWorkload:
    """Create or resume one deterministic, marker-protected workload."""
    resolved = root.resolve()
    _claim_root(resolved, spec)
    created = 0
    retained = 0
    source_bytes = 0
    for index in range(spec.raw_files):
        payload = _raw_text(index, spec.words_per_unit).encode("utf-8")
        path = resolved / "inputs" / "raw" / f"record_{index:04d}.txt"
        existed = path.is_file()
        created += int(_write_if_absent(path, payload))
        retained += int(existed)
        source_bytes += len(payload)
    for index in range(spec.extracted_files):
        payload = bytes(range(256)) * (index + 1)
        path = resolved / "inputs" / "extracted" / f"record_{index:04d}.blob"
        existed = path.is_file()
        created += int(_write_if_absent(path, payload))
        retained += int(existed)
        source_bytes += len(payload)
    extractor = resolved / _EXTRACTOR_NAME
    extractor.write_text(_extractor_source(), encoding="utf-8", newline="\n")
    (resolved / ".vaultragpreprocess.toml").write_text(
        _configuration(resolved, spec), encoding="utf-8", newline="\n"
    )
    return PreparedDocumentWorkload(
        created,
        retained,
        spec.source_files,
        source_bytes,
    )


def measure_document_workload(root: Path) -> DocumentWorkloadMeasurement:
    """Measure production discovery, extraction, chunking, and queue weights."""
    from ...config._settings import get_config
    from ...indexer import DocumentIndexer
    from ...indexer._chunk_worker import (
        DocumentChunkingOptions,
        chunk_document_and_hash_file,
    )
    from ...indexer._streaming import (
        DocumentSliceStreamRequest,
        iter_weighted_document_slices,
    )

    resolved = root.resolve()
    # Measurement only exercises preflight, support-limit, and preprocess-
    # context resolution, none of which touch `self.model` or `self.store`;
    # the constructor requires both, so cast the unused placeholders to
    # their real types rather than loading a model or opening a store here.
    indexer = DocumentIndexer(
        resolved,
        cast("EmbeddingModel", None),
        cast("VaultStore", None),
        content_policy=_policy(),
    )
    preflight = indexer.preflight_content()
    limits = indexer._support_limits()
    prep = indexer._preprocess_context(preflight.policy, limits)
    execution_policy = indexer._execution_policy(preflight.policy)
    source_bytes = sum(path.stat().st_size for path in preflight.files)
    extracted_bytes = 0
    generated_chunks = 0
    weighted_bytes = 0
    queue_bytes = 0
    cfg = get_config()
    with _RuntimeSampler() as sampler:
        for path in preflight.files:
            result = chunk_document_and_hash_file(
                path,
                resolved,
                DocumentChunkingOptions(
                    prep=prep,
                    execution_policy=execution_policy,
                ),
            )
            extracted_bytes += sum(
                len(chunk.payload.content.encode("utf-8")) for chunk in result.chunks
            )
            generated_chunks += len(result.chunks)
            for weighted in iter_weighted_document_slices(
                DocumentSliceStreamRequest(
                    chunks=result.chunks,
                    max_chunks=int(cfg.embedding_batch_size),
                )
            ):
                weighted_bytes += weighted.estimated_bytes
                queue_bytes = max(queue_bytes, weighted.estimated_bytes)
    return DocumentWorkloadMeasurement(
        source_files=len(preflight.files),
        source_bytes=source_bytes,
        extracted_bytes=extracted_bytes,
        generated_chunks=generated_chunks,
        weighted_bytes=weighted_bytes,
        queue_bytes=queue_bytes,
        rss_bytes=sampler.rss_bytes,
        cuda_bytes=sampler.cuda_bytes,
    )


def _validate_measurement(
    root: Path,
    measurement: DocumentWorkloadMeasurement,
) -> None:
    """Apply the configured document profile before loading embedding models."""
    import psutil

    from ..._store_writes import probe_store_volume
    from ...config._settings import get_config
    from ...index_profiles import (
        AdmissionEnvironment,
        IndexDomain,
        SupportMeasurement,
        validate_profile_admission,
    )

    cfg = get_config()
    validate_profile_admission(
        cfg.index_support_profile,
        IndexDomain.DOCUMENT,
        SupportMeasurement(**asdict(measurement)),
        AdmissionEnvironment(
            backend="server" if cfg.qdrant_url else "local",
            available_ram_bytes=int(psutil.virtual_memory().total),
            store_volume=probe_store_volume(root),
        ),
    )


def _run_interrupted_index(
    indexer: DocumentIndexer,
    root: Path,
    *,
    interrupt_after_units: int,
) -> tuple[str, int]:
    """Interrupt after durable units exist and return their generation evidence."""
    from ...config._settings import get_config
    from ...indexer._run_ledger_models import index_run_ledger_path
    from ...job_control import CancelRequested, RunControlToken

    if interrupt_after_units <= 0:
        raise ValueError("interrupt_after_units must be positive")
    token = RunControlToken()
    failures: list[BaseException] = []

    worker = threading.Thread(
        target=_capture_interrupted_run,
        args=(indexer, token, failures),
        name="document-acceptance-interrupt",
    )
    worker.start()
    ledger_path = index_run_ledger_path(root / get_config().data_dir)
    generation_id, confirmed = _wait_for_interruption_boundary(
        ledger_path,
        worker,
        token,
        interrupt_after_units=interrupt_after_units,
    )
    if confirmed < interrupt_after_units:
        token.request_cancel()
        worker.join(timeout=300.0)
        if worker.is_alive():
            raise RuntimeError("document run did not reach a cancellable checkpoint")
        raise RuntimeError("document run produced no durable interruption boundary")
    worker.join(timeout=300.0)
    if worker.is_alive():
        token.request_cancel()
        raise RuntimeError("interrupted document run did not terminate")
    if not failures or not isinstance(failures[0], CancelRequested):
        raise RuntimeError(f"document run did not stop at cancellation: {failures!r}")
    if not generation_id:
        raise RuntimeError("document interruption lost its generation identity")
    return generation_id, confirmed


def _capture_interrupted_run(
    indexer: DocumentIndexer,
    token: RunControlToken,
    failures: list[BaseException],
) -> None:
    """Capture the terminal signal from one benchmark index thread."""
    from ...progress import NullProgressReporter

    try:
        indexer.full_index(
            reporter=NullProgressReporter(),
            preflight=indexer.preflight_content(),
            run_control=token,
        )
    except BaseException as exc:
        failures.append(exc)


def _wait_for_interruption_boundary(
    ledger_path: Path,
    worker: threading.Thread,
    token: RunControlToken,
    *,
    interrupt_after_units: int,
) -> tuple[str, int]:
    """Poll durable units until the requested benchmark interruption point."""
    deadline = time.monotonic() + 600.0
    while time.monotonic() < deadline and worker.is_alive():
        generation_id, confirmed = _document_generation_units(ledger_path)
        if confirmed >= interrupt_after_units:
            token.request_cancel()
            return generation_id, confirmed
        time.sleep(0.01)
    return "", 0


def _document_generation_units(ledger_path: Path) -> tuple[str, int]:
    """Read the latest benchmark generation identity and durable unit count."""
    from ... import store_schema
    from ...indexer._content_policy import ContentKind
    from ...indexer._run_ledger_runtime import RunLedger

    if not ledger_path.is_file():
        return "", 0
    ledger = RunLedger(ledger_path)
    generation = ledger.latest_generation(
        ContentKind.DOCUMENT,
        collection_identity=store_schema.DOCUMENT_COLLECTION,
    )
    if generation is None:
        return "", 0
    units = tuple(ledger.iter_units(generation.generation_id))
    return generation.generation_id, len(units)


def run_document_acceptance(
    root: Path,
    spec: DocumentWorkloadSpec,
    *,
    local_files_only: bool,
    interrupt_after_units: int = 1,
) -> DocumentAcceptanceReport:
    """Run real extraction, CUDA embedding, Qdrant writes, interruption, and resume."""
    from ... import EmbeddingModel, store_schema
    from ...config._settings import get_config
    from ...indexer import DocumentIndexer
    from ...indexer._content_policy import ContentKind
    from ...indexer._run_ledger_models import index_run_ledger_path
    from ...indexer._run_ledger_runtime import RunLedger
    from ...progress import NullProgressReporter
    from ...store_runtime import VaultStore

    resolved = root.resolve()
    prepared = prepare_document_workload(resolved, spec)
    measurement = measure_document_workload(resolved)
    _validate_measurement(resolved, measurement)
    cfg = get_config()
    model = EmbeddingModel(local_files_only=local_files_only)
    store = VaultStore(resolved)
    try:
        interrupted = DocumentIndexer(
            resolved,
            model,
            store,
            content_policy=_policy(),
        )
        generation_id, confirmed_before = _run_interrupted_index(
            interrupted,
            resolved,
            interrupt_after_units=interrupt_after_units,
        )
        resumed = DocumentIndexer(
            resolved,
            model,
            store,
            content_policy=_policy(),
        )
        with _RuntimeSampler() as sampler:
            result: IndexResult = resumed.full_index(
                reporter=NullProgressReporter(),
                preflight=resumed.preflight_content(),
            )
        ledger = RunLedger(index_run_ledger_path(resolved / cfg.data_dir))
        published = ledger.latest_generation(
            ContentKind.DOCUMENT,
            collection_identity=store_schema.DOCUMENT_COLLECTION,
        )
        if published is None or published.generation_id != generation_id:
            raise RuntimeError(
                "document resume did not continue its interrupted generation"
            )
        confirmed_after = len(tuple(ledger.iter_units(generation_id)))
        if confirmed_after <= confirmed_before:
            raise RuntimeError("document resume made no durable forward progress")
        if result.files != spec.source_files or store.count_document() != result.total:
            raise RuntimeError("document result, workload, and collection diverged")
        final_measurement = {
            **asdict(measurement),
            "rss_bytes": max(measurement.rss_bytes, sampler.rss_bytes),
            "cuda_bytes": max(measurement.cuda_bytes, sampler.cuda_bytes),
        }
        return DocumentAcceptanceReport(
            schema_version=_SCHEMA_VERSION,
            root=str(resolved),
            profile=str(cfg.index_support_profile),
            backend="server" if cfg.qdrant_url else "local",
            prepared=asdict(prepared),
            measurement=final_measurement,
            result=cast("dict[str, object]", asdict(result)),
            interrupted_generation=generation_id,
            confirmed_before_resume=confirmed_before,
            confirmed_after_resume=confirmed_after,
        )
    finally:
        store.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--raw-files", type=int, default=4)
    parser.add_argument("--extracted-files", type=int, default=4)
    parser.add_argument("--units", type=int, default=3)
    parser.add_argument("--words", type=int, default=160)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--accept", action="store_true")
    parser.add_argument("--local-files-only", action="store_true")
    parser.add_argument("--interrupt-after-units", type=int, default=1)
    parser.add_argument("--json", type=Path, default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Prepare and measure the named document workload."""
    args = _parser().parse_args(argv)
    spec = DocumentWorkloadSpec(
        args.raw_files,
        args.extracted_files,
        args.units,
        args.words,
    )
    prepared = prepare_document_workload(args.root, spec)
    payload: dict[str, object] = {
        "schema_version": _SCHEMA_VERSION,
        "root": str(args.root.resolve()),
        "spec": asdict(spec),
        "prepared": asdict(prepared),
    }
    if args.accept:
        payload = asdict(
            run_document_acceptance(
                args.root,
                spec,
                local_files_only=args.local_files_only,
                interrupt_after_units=args.interrupt_after_units,
            )
        )
    elif not args.prepare_only:
        payload["measurement"] = asdict(measure_document_workload(args.root))
    if args.json is not None:
        _write_json(args.json, payload)
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
