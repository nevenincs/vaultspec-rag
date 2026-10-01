"""On-demand service resource readings and observed TCP peers."""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import psutil

from ._job_evidence import gpu_pressure_snapshot, process_cpu_snapshot
from .config._settings import get_config

MAX_OBSERVED_CLIENTS = 256
DEFAULT_OBSERVED_CLIENTS = 64
_HOST_CPU_SAMPLE_SECONDS = 5.0
_host_cpu_lock = threading.Lock()
_host_cpu_sample: tuple[float, float | None] | None = None
_host_cpu_primed_threads: set[int] = set()


def _host_cpu_utilization() -> float | None:
    global _host_cpu_sample
    now = time.monotonic()
    with _host_cpu_lock:
        prior = _host_cpu_sample
        if prior is not None and now - prior[0] < _HOST_CPU_SAMPLE_SECONDS:
            return prior[1]
        try:
            reading = float(psutil.cpu_percent(interval=None))
        except (psutil.Error, OSError):
            reading = None
        thread_id = threading.get_ident()
        sample = reading if thread_id in _host_cpu_primed_threads else None
        if reading is not None:
            # psutil's nonblocking system counter is local to the calling
            # thread. A new worker must prime its own baseline before use.
            live_threads = {thread.ident for thread in threading.enumerate()}
            _host_cpu_primed_threads.intersection_update(live_threads)
            _host_cpu_primed_threads.add(thread_id)
        _host_cpu_sample = (now, sample)
        return sample


def _ram_observation(process: psutil.Process) -> dict[str, object]:
    result: dict[str, object] = {
        "available": False,
        "process_rss_bytes": None,
        "total_bytes": None,
        "available_bytes": None,
    }
    try:
        memory = psutil.virtual_memory()
        result.update(total_bytes=memory.total, available_bytes=memory.available)
        result["process_rss_bytes"] = process.memory_info().rss
        result["available"] = True
    except (psutil.Error, OSError) as exc:
        result["reason"] = type(exc).__name__
    return result


def _disk_observation() -> dict[str, object]:
    target = Path(get_config().qdrant_storage_dir).expanduser().resolve()
    result: dict[str, object] = {
        "path": str(target),
        "available": False,
        "total_bytes": None,
        "used_bytes": None,
        "free_bytes": None,
    }
    try:
        volume = target
        while not volume.exists() and volume != volume.parent:
            volume = volume.parent
        disk = psutil.disk_usage(str(volume))
        result.update(
            available=True,
            volume_path=str(volume),
            total_bytes=disk.total,
            used_bytes=disk.used,
            free_bytes=disk.free,
        )
    except (psutil.Error, OSError) as exc:
        result["reason"] = type(exc).__name__
    return result


def _client_observation(
    process: psutil.Process, *, port: int, limit: int
) -> dict[str, object]:
    result: dict[str, object] = {
        "kind": "observed_tcp_connections",
        "available": False,
        "items": [],
        "total": None,
        "returned": 0,
        "truncated": False,
        "limit": limit,
    }
    try:
        peers = sorted(
            (connection.raddr.ip, connection.raddr.port)
            for connection in process.net_connections(kind="tcp")
            if connection.status == psutil.CONN_ESTABLISHED
            and connection.laddr
            and connection.laddr.port == port
            and connection.raddr
        )
        result.update(
            available=True,
            items=[
                {"host": host, "port": peer_port, "status": "ESTABLISHED"}
                for host, peer_port in peers[:limit]
            ],
            total=len(peers),
            returned=min(limit, len(peers)),
            truncated=len(peers) > limit,
        )
    except (psutil.Error, OSError) as exc:
        result["reason"] = type(exc).__name__
    return result


def runtime_observations(
    *, port: int, client_limit: int = DEFAULT_OBSERVED_CLIENTS
) -> dict[str, object]:
    """Observe this process; TCP peers are transport evidence, not sessions."""
    limit = max(1, min(MAX_OBSERVED_CLIENTS, client_limit))
    process = psutil.Process()
    cpu = process_cpu_snapshot()
    cpu["system_utilization_percent"] = _host_cpu_utilization()
    cpu["process_percent_basis"] = "one_cpu_core"
    gpu = gpu_pressure_snapshot()
    if gpu.get("available") is False:
        gpu["reason"] = "accelerator_measurement_unavailable"
    return {
        "ok": True,
        "observed_at": time.time(),
        "pid": os.getpid(),
        "cpu": cpu,
        "ram": _ram_observation(process),
        "gpu": gpu,
        "disk": _disk_observation(),
        "clients": _client_observation(process, port=port, limit=limit),
    }
