"""Module-level singleton holder for the shared :class:`ServiceRegistry`.

Breaks the cycle that would otherwise exist if both ``api.py`` and
``server/_main.py`` tried to import ``_registry`` from each other.  Both
modules depend on this one instead.
"""

from __future__ import annotations

import sys
import threading

from .service import ServiceRegistry

__all__ = ["discard_job_manager", "get_registry", "reset_registry"]

_registry: ServiceRegistry | None = None
_REGISTRY_LOCK = threading.Lock()


def _rebind_server_alias(registry: ServiceRegistry) -> None:
    """Point the server package's cached alias at the live singleton.

    ``server._state`` caches this singleton at import time, and every consumer
    reads it as ``server._registry`` on the package namespace precisely so a
    rebind there is observed. Rebuilding the singleton without rebinding leaves
    the watcher driving a closed registry while the dispatcher drives the new
    one, and the two double-open the same non-parallel-safe local store.

    Only rebinds a package that is already imported: importing it here would
    invert the dependency this module exists to break.
    """
    server = sys.modules.get("vaultspec_rag.server")
    if server is not None:
        # Rebind the module global directly: the name is package-private and
        # absent from ``ModuleType``, so an attribute assignment is only
        # expressible here as an unchecked one.
        server.__dict__["_registry"] = registry


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
            _rebind_server_alias(_registry)
        return _registry


def discard_job_manager() -> None:
    """Drop the singleton's cached job manager, if a singleton exists.

    Deliberately does not build a registry to clear one: no registry means no
    cached manager, and constructing one here would resurrect a singleton a
    caller had just torn down.
    """
    with _REGISTRY_LOCK:
        if _registry is not None:
            _registry.discard_job_manager()


def reset_registry() -> None:
    """Tear down the singleton (test-only).

    Closes all slots on the current registry via ``close_all`` and
    drops the reference so the next ``get_registry()`` call builds a
    fresh instance.  Safe to call when no registry exists.

    Between this call and that next ``get_registry()`` there is no singleton,
    so ``server._registry`` still names the instance just closed.  Reach the
    registry through ``get_registry()``, which rebinds that alias as it
    rebuilds; reading ``server._registry`` directly in the gap hands back a
    closed instance that ``prepare_startup()`` will silently reopen.
    """
    global _registry
    with _REGISTRY_LOCK:
        if _registry is not None:
            _registry.close_all()
            _registry = None
