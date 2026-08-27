"""One in-thread host for the real authenticated service routes.

A test that has to be *discovered* by the production client, rather than told
where to look, needs three things agreeing with each other: a bound listener
serving the real route table, a discovery record naming that port and the
token the routes check, and a registry whose quiesce state the routes report.
This module owns that arrangement so the modules that need it import it
instead of restating it.

The daemon lifespan is deliberately absent: these hosts serve routes and hold
registry state, and never load a model or touch the GPU.
"""

from __future__ import annotations

import contextlib
import os
import threading
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final, NamedTuple

import uvicorn

from ..config._paths import SERVICE_STATUS_FILENAME
from ..service import ServiceRegistry
from ..serviceclient._compat import SERVICE_VERSION_FIELD, local_package_version
from ..serviceclient._discovery import (
    HEARTBEAT_STALENESS_SECONDS,
    SERVICE_DISCOVERY_SCHEMA,
    SERVICE_DISCOVERY_VERSION,
    _replace_service_status,
)
from ..serviceclient._transport import _try_http_admin
from ._ports import free_loopback_port

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

__all__ = [
    "CHILD_PROCESS_TIMEOUT_SECONDS",
    "PROCESS_TIMEOUT_SECONDS",
    "SERVICE_TOKEN",
    "ProductionService",
    "production_service",
    "publish_discovery",
]

#: The shared secret the published discovery record and the hosted route table
#: agree on, so an authenticated client call resolves it the way it does
#: against a real daemon.
SERVICE_TOKEN: Final = "production-route-host-token"

#: Ceiling on every wait for a process or thread to reach the state a test
#: needs. Generous on purpose: it costs nothing when green and only decides how
#: long a genuinely wedged host takes to be reported.
PROCESS_TIMEOUT_SECONDS: Final = 10.0

#: Ceiling on a wait for a SPAWNED CHILD to reach the state a test needs.
#: Separate from the above because the two are not the same wait: a child has
#: to be scheduled, start an interpreter and import this package before it can
#: reach any marker at all, and under a parallel run those precede the work by
#: seconds. Ten was enough for an in-process wait and far too little for this
#: one, which is how a correct borrower was reported as "never reached work".
#:
#: Mutation: set to 0.01. The borrower case fails with exactly the message CI
#: reported, so this bound - not the code under test - is what that failure was
#: about. Restored, and it passes.
CHILD_PROCESS_TIMEOUT_SECONDS: Final = 120.0


class ProductionService(NamedTuple):
    """One real route host and the registry whose state it exposes."""

    registry: ServiceRegistry
    port: int
    server: uvicorn.Server
    thread: threading.Thread

    def stop(self) -> None:
        """Stop the real HTTP listener without changing registry state."""
        self.server.should_exit = True
        self.thread.join(timeout=PROCESS_TIMEOUT_SECONDS)
        assert not self.thread.is_alive(), "production route server did not stop"


def publish_discovery(
    status_dir: Path,
    *,
    port: int,
    heartbeat: str | None = None,
) -> None:
    """Publish the real route host through the production discovery writer."""
    _replace_service_status(
        {
            "pid": os.getpid(),
            "port": port,
            "schema": SERVICE_DISCOVERY_SCHEMA,
            "version": SERVICE_DISCOVERY_VERSION,
            SERVICE_VERSION_FIELD: local_package_version(),
            "service_token": SERVICE_TOKEN,
            "last_heartbeat": heartbeat
            or datetime.now(UTC).isoformat(timespec="seconds"),
            "stale_after_s": HEARTBEAT_STALENESS_SECONDS,
        },
        path=status_dir / SERVICE_STATUS_FILENAME,
    )


@contextlib.contextmanager
def production_service(status_dir: Path) -> Generator[ProductionService]:
    """Serve authenticated production routes with no daemon lifespan or GPU."""
    from ..server import ServerRouteRuntime, create_http_app

    registry = ServiceRegistry()
    port = free_loopback_port()
    server = uvicorn.Server(
        uvicorn.Config(
            create_http_app(
                ServerRouteRuntime(
                    token=SERVICE_TOKEN,
                    registry=registry,
                    port=port,
                ),
                lifespan=None,
            ),
            host="127.0.0.1",
            port=port,
            log_config=None,
            access_log=False,
            lifespan="off",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    service = ProductionService(registry, port, server, thread)
    thread.start()
    try:
        deadline = time.monotonic() + PROCESS_TIMEOUT_SECONDS
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started, "production route server did not start"
        publish_discovery(status_dir, port=port)
        yield service
    finally:
        if thread.is_alive():
            # A test that paused this host leaves it quiesced; resume before
            # the listener goes away so teardown never depends on the caller
            # having unwound its own pause. Skipped when the caller already
            # stopped the listener, because a refused connect is a slow way to
            # learn nothing.
            _try_http_admin("resume_service", {}, port)
            service.stop()
        # Withdraw the record this block published. The listener is gone, so a
        # record naming its port would advertise an address nothing answers on,
        # and the production client has no way to tell that from a wedged
        # daemon: a caller that runs a service-first command after this block
        # would be routed at the dead port instead of taking the local path it
        # would have taken had the host never existed.
        (status_dir / SERVICE_STATUS_FILENAME).unlink(missing_ok=True)
