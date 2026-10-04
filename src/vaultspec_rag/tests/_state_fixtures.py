"""Process-state resets for tests.

Production creates each of these once per process and never tears it down. A
test that needs a clean one drops it here, the way the owning module would.
"""

from __future__ import annotations

from .. import _integrity_remediation, concurrency, pressure, registry
from ..server import _state as server_state


def reset_observations() -> None:
    """Forget every recorded integrity observation."""
    with _integrity_remediation._STATE_LOCK:
        _integrity_remediation._OBSERVATIONS.clear()


def reset_limiters() -> None:
    """Drop the capacity limiters so the next read rebuilds them."""
    with concurrency._lock:
        concurrency._search_limiter = None
        concurrency._index_limiter = None
        concurrency._encode_limiter = None


def reset_pressure_evaluator() -> None:
    """Drop the cached machine-pressure evaluator."""
    with pressure._evaluator_lock:
        pressure._evaluator = None


def reset_registry() -> None:
    """Close every project slot and drop the process registry."""
    with registry._REGISTRY_LOCK:
        if registry._registry is not None:
            registry._registry.close_all()
            registry._registry = None


def reset_metrics() -> None:
    """Zero every service counter and gauge."""
    with server_state._metrics_lock:
        for key in server_state._counters:
            server_state._counters[key] = 0
        for key in server_state._gauges:
            server_state._gauges[key] = 0.0
