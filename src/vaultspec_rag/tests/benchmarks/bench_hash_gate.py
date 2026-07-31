"""Benchmark: hashing-loop overhead attribution and stat-gate throughput.

The vault hashing loop once ran at ~30 files/s over small markdown files
while bare blake2b runs thousands per second: the per-file cost was overhead,
not hashing. This benchmark keeps that attribution durable by measuring each
component in isolation - the raw digest, the stat probe, a run-control
checkpoint, and the job-state persist a service progress tick pays - and then
the production batched loop cold (no gate evidence) and warm (gate answers
from stat), in files per second.

CPU and disk only: no model, no store, no service. Asserts ratios, never
wall-clock, so it holds on any machine. Marked ``performance``; invoke with
pytest ``-m performance``.
"""

from __future__ import annotations

import hashlib
import os
import time
from typing import TYPE_CHECKING

import pytest

from ...indexer._stat_gate import StatEvidenceGate, hash_paths
from ...job_control import RunControlToken
from ...job_persistence import PersistedManagerState, save_persisted_state

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from pytest import TempPathFactory

_N_FILES = 2000
_FILE_BYTES = 1500


def _build_corpus(root: Path) -> list[tuple[str, Path]]:
    root.mkdir(parents=True, exist_ok=True)
    body = b"lorem ipsum dolor sit amet, consectetur adipiscing elit\n" * 40
    items: list[tuple[str, Path]] = []
    for i in range(_N_FILES):
        path = root / f"doc_{i:05d}.md"
        path.write_bytes((b"# doc %05d\n" % i + body)[:_FILE_BYTES])
        # Age past the racy window so recorded evidence is trustworthy.
        stat = path.stat()
        os.utime(path, (stat.st_mtime - 60, stat.st_mtime - 60))
        items.append((f"doc_{i:05d}.md", path))
    return items


def _per_call_ms(call: Callable[[], object], rounds: int) -> float:
    start = time.perf_counter()
    for _ in range(rounds):
        call()
    return (time.perf_counter() - start) / rounds * 1000


@pytest.mark.performance
def test_hash_gate_overhead_breakdown_and_throughput(
    tmp_path_factory: TempPathFactory,
) -> None:
    root = tmp_path_factory.mktemp("bench-hash-gate")
    items = _build_corpus(root / "corpus")
    paths = [path for _, path in items]

    # --- per-component floors ---
    def digest_all() -> None:
        for path in paths:
            with open(path, "rb") as stream:
                hashlib.file_digest(stream, "blake2b").hexdigest()

    start = time.perf_counter()
    digest_all()
    digest_ms = (time.perf_counter() - start) / _N_FILES * 1000

    start = time.perf_counter()
    for path in paths:
        os.stat(path)
    stat_ms = (time.perf_counter() - start) / _N_FILES * 1000

    token = RunControlToken()
    checkpoint_ms = _per_call_ms(token.checkpoint, 100_000)

    # What one unbatched service progress tick pays: a full job-state
    # persist (json + fsync + atomic replace) through the real writer.
    state_path = root / "state" / "jobs-state.json"
    state_path.parent.mkdir()
    state = PersistedManagerState(jobs=(), bindings=())
    save_persisted_state(state_path, state)
    advance_persist_ms = _per_call_ms(
        lambda: save_persisted_state(state_path, state), 100
    )

    # --- production batched loop, cold then warm ---
    gate = StatEvidenceGate.load(root / "gate.json")
    start = time.perf_counter()
    cold = hash_paths(gate, items, run_control=token)
    cold_s = time.perf_counter() - start
    gate.persist()
    assert not cold.failures
    assert len(cold.hashes) == _N_FILES

    warm_gate = StatEvidenceGate.load(root / "gate.json")
    start = time.perf_counter()
    warm = hash_paths(warm_gate, items, run_control=token)
    warm_s = time.perf_counter() - start
    assert warm.hashes == cold.hashes
    assert warm_gate.reused == _N_FILES

    cold_fps = _N_FILES / cold_s
    warm_fps = _N_FILES / warm_s
    print(
        f"\n[hash-gate benchmark] files={_N_FILES} size={_FILE_BYTES}B\n"
        f"  raw open+digest      {digest_ms:8.4f} ms/file\n"
        f"  os.stat              {stat_ms:8.4f} ms/file\n"
        f"  checkpoint           {checkpoint_ms:8.4f} ms/call\n"
        f"  advance persist      {advance_persist_ms:8.4f} ms/call\n"
        f"  batched loop cold    {cold_s / _N_FILES * 1000:8.4f} ms/file"
        f"  ({cold_fps:,.0f} files/s)\n"
        f"  batched loop warm    {warm_s / _N_FILES * 1000:8.4f} ms/file"
        f"  ({warm_fps:,.0f} files/s)",
    )

    # The attribution the loops are built around: one unbatched progress
    # persist outweighs the entire per-file hashing work by an order of
    # magnitude, and a warm stat probe undercuts a full read.
    assert advance_persist_ms > 10 * digest_ms
    assert stat_ms < digest_ms
    # The warm gate must beat cold hashing - the reason the gate exists.
    assert warm_s < cold_s
