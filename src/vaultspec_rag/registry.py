"""Module-level singleton holder for the shared :class:`ServiceRegistry`.

Breaks the cycle that would otherwise exist if both ``api.py`` and
``server/_main.py`` tried to import ``_registry`` from each other.  Both
modules depend on this one instead.
"""

from __future__ import annotations

import threading

from .service import ServiceRegistry

__all__ = ["get_registry", "reset_registry"]

_registry: ServiceRegistry | None = None
_REGISTRY_LOCK = threading.Lock()


def get_registry() -> ServiceRegistry:
    """Return the process-wide :class:`ServiceRegistry` singleton.

    Thread-safe: uses a double-checked ``threading.Lock`` so concurrent
    first-callers never observe a partially-initialised registry.

    Returns:
        The singleton ``ServiceRegistry`` instance.
    """
    global _registry
    if _registry is not None:
        return _registry
    with _REGISTRY_LOCK:
        if _registry is None:
            _registry = ServiceRegistry()
        return _registry


def reset_registry() -> None:
    """Tear down the singleton (test-only).

    Closes all slots on the current registry via ``close_all`` and
    drops the reference so the next ``get_registry()`` call builds a
    fresh instance.  Safe to call when no registry exists.
    """
    global _registry
    with _REGISTRY_LOCK:
        if _registry is not None:
            _registry.close_all()
            _registry = None
