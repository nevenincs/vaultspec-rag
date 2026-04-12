"""Lightweight RSS + CUDA memory probe for index pipelines.

Gated by the ``VAULTSPEC_RAG_MEMORY_PROBE`` env var.  When enabled the
probe records resident-set size (RSS) and ``torch.cuda.memory_allocated/
reserved`` at named checkpoints and emits a structured report.

The probe is intentionally self-contained: it has no hard dependency on
any other indexer module so it can be used from tests, benchmarks, and
ad-hoc scripts without pulling the full import graph.
"""

from __future__ import annotations

import contextlib
import logging
import os
import threading
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

__all__ = [
    "MemoryProbe",
    "MemorySample",
    "current_cuda_mb",
    "current_rss_mb",
    "is_enabled",
]


ENV_VAR = "VAULTSPEC_RAG_MEMORY_PROBE"


def is_enabled() -> bool:
    """Return ``True`` when the memory probe is active.

    The probe activates when ``VAULTSPEC_RAG_MEMORY_PROBE`` is set to a
    non-empty, non-``0`` value.
    """
    value = os.environ.get(ENV_VAR, "")
    return bool(value) and value != "0"


def current_rss_mb() -> float:
    """Return current process RSS in megabytes.

    ``psutil`` is a hard dependency of the RAG package so this is
    always available; the import is deferred only to keep cold-path
    startup cheap when the probe is disabled.
    """
    import psutil

    return psutil.Process(os.getpid()).memory_info().rss / (1024.0 * 1024.0)


def current_cuda_mb() -> tuple[float, float]:
    """Return ``(allocated_mb, reserved_mb)`` for the active CUDA device.

    Returns zeros when torch is not importable or CUDA is unavailable —
    the probe must never crash host code.
    """
    try:
        import torch
    except ImportError:
        return (0.0, 0.0)
    if not torch.cuda.is_available():
        return (0.0, 0.0)
    allocated = torch.cuda.memory_allocated() / (1024.0 * 1024.0)
    reserved = torch.cuda.memory_reserved() / (1024.0 * 1024.0)
    return (allocated, reserved)


@dataclass
class MemorySample:
    """A single checkpoint recorded by :class:`MemoryProbe`.

    Attributes:
        label: Human-readable checkpoint name (e.g. ``"after dense
            encode batch 3"``).
        rss_mb: Process resident-set size at the checkpoint.
        cuda_allocated_mb: Live ``torch.cuda.memory_allocated`` value.
        cuda_reserved_mb: Live ``torch.cuda.memory_reserved`` value.
        wall_s: Seconds since the probe was constructed.
    """

    label: str
    rss_mb: float
    cuda_allocated_mb: float
    cuda_reserved_mb: float
    wall_s: float


@dataclass
class MemoryProbe:
    """Record RSS + CUDA memory checkpoints during an index pipeline.

    The probe is a no-op when :func:`is_enabled` returns ``False``.  It
    also runs a background sampler that tracks peak RSS between
    checkpoints so that transient spikes (e.g. during a single encode
    batch) are captured even if the caller only adds coarse-grained
    markers.
    """

    name: str = "indexer"
    samples: list[MemorySample] = field(default_factory=list)
    start_rss_mb: float = 0.0
    peak_rss_mb: float = 0.0
    _t0: float = 0.0
    _sampler_thread: threading.Thread | None = None
    _sampler_stop: threading.Event = field(default_factory=threading.Event)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self) -> None:
        if not is_enabled():
            return
        self._t0 = time.perf_counter()
        self.start_rss_mb = current_rss_mb()
        self.peak_rss_mb = self.start_rss_mb
        self._start_sampler()

    def _start_sampler(self) -> None:
        def _run() -> None:
            while not self._sampler_stop.wait(0.25):
                rss = current_rss_mb()
                with self._lock:
                    if rss > self.peak_rss_mb:
                        self.peak_rss_mb = rss

        thread = threading.Thread(
            target=_run,
            name=f"memory-probe-{self.name}",
            daemon=True,
        )
        thread.start()
        self._sampler_thread = thread

    def checkpoint(self, label: str) -> MemorySample | None:
        """Record a checkpoint and return the sample.

        Returns ``None`` when the probe is disabled.
        """
        if not is_enabled():
            return None
        rss = current_rss_mb()
        allocated, reserved = current_cuda_mb()
        with self._lock:
            if rss > self.peak_rss_mb:
                self.peak_rss_mb = rss
        sample = MemorySample(
            label=label,
            rss_mb=rss,
            cuda_allocated_mb=allocated,
            cuda_reserved_mb=reserved,
            wall_s=time.perf_counter() - self._t0,
        )
        self.samples.append(sample)
        logger.info(
            "[memory-probe %s] %s rss=%.0fMB cuda_alloc=%.0fMB "
            "cuda_reserved=%.0fMB t=%.2fs",
            self.name,
            label,
            sample.rss_mb,
            sample.cuda_allocated_mb,
            sample.cuda_reserved_mb,
            sample.wall_s,
        )
        return sample

    @contextlib.contextmanager
    def phase(self, label: str):
        """Context manager wrapping a phase with enter/exit checkpoints."""
        self.checkpoint(f"enter:{label}")
        try:
            yield
        finally:
            self.checkpoint(f"exit:{label}")

    def stop(self) -> None:
        """Stop the background sampler thread."""
        if self._sampler_thread is None:
            return
        self._sampler_stop.set()
        self._sampler_thread.join(timeout=1.0)
        self._sampler_thread = None

    def report(self) -> str:
        """Render a human-readable report of recorded checkpoints."""
        if not self.samples:
            return f"[memory-probe {self.name}] disabled or no samples"
        lines = [
            f"[memory-probe {self.name}] start_rss={self.start_rss_mb:.0f}MB "
            f"peak_rss={self.peak_rss_mb:.0f}MB delta="
            f"{self.peak_rss_mb - self.start_rss_mb:+.0f}MB",
        ]
        prev_rss = self.start_rss_mb
        for s in self.samples:
            delta = s.rss_mb - prev_rss
            lines.append(
                f"  {s.wall_s:6.2f}s  rss={s.rss_mb:7.0f}MB "
                f"({delta:+6.0f})  cuda_alloc={s.cuda_allocated_mb:6.0f}MB  "
                f"reserved={s.cuda_reserved_mb:6.0f}MB  {s.label}"
            )
            prev_rss = s.rss_mb
        return "\n".join(lines)
