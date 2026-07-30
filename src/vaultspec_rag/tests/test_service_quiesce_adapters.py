"""CPU-only adapter guards over the production quiesce route contracts."""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import uvicorn

from ..config._types import EnvVar
from ..service_quiesce import (
    QUIESCE_ENVELOPE_FIELDS,
    QuiesceSnapshot,
    QuiesceState,
)
from ._ports import free_loopback_port
from .conftest import managed_env

if TYPE_CHECKING:
    from collections.abc import Generator

pytestmark = [pytest.mark.unit]

_SERVICE_TOKEN = "quiesce-adapter-route-token"


def test_the_envelope_field_set_is_derived_from_the_snapshot() -> None:
    """The published vocabulary must be what the controller actually renders.

    ``QUIESCE_ENVELOPE_FIELDS`` is derived from the dataclass, while
    ``as_envelope`` builds a dict literal; nothing but this makes the two agree.
    Adapters reject a block whose key set differs from the constant, so a field
    added to one and not the other would not fail here first - it would show up
    as every surface reporting the daemon unavailable.

    Mutation proof: renaming ``vram_released`` in ``as_envelope`` alone fails
    this on the key-set comparison below, not on an import or a lookup.
    """
    snapshot = QuiesceSnapshot(
        state=QuiesceState.RUNNING,
        admission_epoch=0,
        admissions_open=True,
        active_compute_tickets=0,
        drain_complete=False,
        vram_released=False,
        safe_to_borrow_gpu=False,
        pause_requested_at=None,
        drain_acknowledged_at=None,
        quiesced_at=None,
        warming_started_at=None,
        failure_reason=None,
    )
    assert set(snapshot.as_envelope()) == set(QUIESCE_ENVELOPE_FIELDS)


def _run_mcp_service_state_probe(tmp_path: Path) -> subprocess.CompletedProcess[str]:
    """Drive MCP through discovery to the production service-state route."""
    probe = r"""
import asyncio
import json
import os
import sys
import threading
import time
from pathlib import Path

import uvicorn
from starlette.applications import Starlette

base = Path(sys.argv[1])
status_dir = base / "status"
workspace = base / "workspace"
(workspace / ".vault").mkdir(parents=True)
(workspace / ".vaultspec").mkdir()
os.environ["VAULTSPEC_RAG_STATUS_DIR"] = str(status_dir)
os.environ["VAULTSPEC_RAG_QDRANT_STORAGE_DIR"] = str(base / "qdrant")
os.environ["VAULTSPEC_RAG_LOCAL_ONLY"] = "true"

from vaultspec_rag.config._settings import reset_config

reset_config()

from vaultspec_rag.config._paths import SERVICE_STATUS_FILENAME
from vaultspec_rag.server import ServerRouteRuntime, create_http_app
from vaultspec_rag.server._routes import ROUTES
from vaultspec_rag.service import ServiceRegistry
from vaultspec_rag.serviceclient._compat import (
    SERVICE_VERSION_FIELD,
    local_package_version,
)
from vaultspec_rag.serviceclient._discovery import (
    SERVICE_DISCOVERY_SCHEMA,
    SERVICE_DISCOVERY_VERSION,
    _replace_service_status,
)
from vaultspec_rag.serviceclient._transport import _try_http_admin
from vaultspec_rag.tests._ports import free_loopback_port

token = "quiesce-adapter-route-token"
port = free_loopback_port()
server = uvicorn.Server(
    uvicorn.Config(
        create_http_app(
            ServerRouteRuntime(
                token=token,
                registry=ServiceRegistry(),
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
thread.start()
try:
    deadline = time.monotonic() + 5.0
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.01)
    assert server.started
    _replace_service_status(
        {
            "pid": os.getpid(),
            "port": port,
            "schema": SERVICE_DISCOVERY_SCHEMA,
            "version": SERVICE_DISCOVERY_VERSION,
            SERVICE_VERSION_FIELD: local_package_version(),
            "service_token": token,
        },
        path=status_dir / SERVICE_STATUS_FILENAME,
    )

    pause = _try_http_admin("pause_service", {}, port)
    assert pause is not None and pause["ok"] is True, pause
    direct = _try_http_admin(
        "get_service_state", {"project_root": str(workspace)}, port
    )
    assert direct is not None, direct
    forbidden = {"torch", "sentence_transformers", "transformers", "qdrant_client"}
    route_imports = forbidden.intersection(
        name.split(".", 1)[0] for name in sys.modules
    )

    from vaultspec_rag.mcp._tools import get_index_status
    from vaultspec_rag.service_quiesce import QUIESCE_ENVELOPE_FIELDS

    result = asyncio.run(get_index_status(project_root=str(workspace)))
    assert result == direct, (result, direct)
    quiesce = result["quiesce"]
    assert isinstance(quiesce, dict), quiesce
    assert set(quiesce) == set(QUIESCE_ENVELOPE_FIELDS), quiesce
    assert quiesce["state"] == "quiesced", quiesce
    assert quiesce["vram_released"] is True, quiesce
    assert quiesce["safe_to_borrow_gpu"] is True, quiesce
    mcp_imports = forbidden.intersection(name.split(".", 1)[0] for name in sys.modules)
    assert mcp_imports == route_imports, (route_imports, mcp_imports)
    print(json.dumps(result))
finally:
    _try_http_admin("resume_service", {}, port)
    server.should_exit = True
    thread.join(timeout=5)
    assert not thread.is_alive()
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path.cwd() / "src")
    return subprocess.run(
        [sys.executable, "-c", probe, str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )


def test_mcp_service_state_preserves_the_production_quiesce_block(
    tmp_path: Path,
) -> None:
    """MCP returns the bare authenticated route document without inference.

    Mutation: wrap the successful service-state result in a new envelope.
    Exact equality with the same production route response fails, proving the
    adapter cannot hide, rename, or recreate the controller-owned block.
    """
    completed = _run_mcp_service_state_probe(tmp_path)

    assert completed.returncode == 0, completed.stderr
    from ..jobs import mapping

    result = mapping(json.loads(completed.stdout))
    quiesce = mapping(result.get("quiesce"))
    assert set(quiesce) == QUIESCE_ENVELOPE_FIELDS
    assert quiesce["state"] == "quiesced"
    assert quiesce["vram_released"] is True
    assert quiesce["safe_to_borrow_gpu"] is True


def _publish_service_discovery(status_dir: Path, *, port: int) -> None:
    """Publish the route host through the production discovery writer."""
    from ..config._paths import SERVICE_STATUS_FILENAME
    from ..serviceclient._compat import SERVICE_VERSION_FIELD, local_package_version
    from ..serviceclient._discovery import (
        SERVICE_DISCOVERY_SCHEMA,
        SERVICE_DISCOVERY_VERSION,
        _replace_service_status,
    )

    _replace_service_status(
        {
            "pid": os.getpid(),
            "port": port,
            "schema": SERVICE_DISCOVERY_SCHEMA,
            "version": SERVICE_DISCOVERY_VERSION,
            SERVICE_VERSION_FIELD: local_package_version(),
            "service_token": _SERVICE_TOKEN,
        },
        path=status_dir / SERVICE_STATUS_FILENAME,
    )


@contextlib.contextmanager
def _production_routes(status_dir: Path) -> Generator[int]:
    """Serve the real route table without starting the daemon lifespan."""
    from ..server import ServerRouteRuntime, create_http_app
    from ..service import ServiceRegistry
    from ..serviceclient._transport import _try_http_admin

    port = free_loopback_port()
    server = uvicorn.Server(
        uvicorn.Config(
            create_http_app(
                ServerRouteRuntime(
                    token=_SERVICE_TOKEN,
                    registry=ServiceRegistry(),
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
    thread.start()
    try:
        deadline = time.monotonic() + 5.0
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started
        _publish_service_discovery(status_dir, port=port)
        yield port
    finally:
        _try_http_admin("resume_service", {}, port)
        server.should_exit = True
        thread.join(timeout=5)
        assert not thread.is_alive()


async def _paint_quiesce_jobs_tui(
    *,
    port: int,
    job_args: dict[str, object],
) -> tuple[object, str, str | None]:
    """Run the Textual jobs surface over authenticated production transport."""
    from ..cli._jobs_tui import ServerWatchApp
    from ..serviceclient._transport import _try_http_admin

    def fetch() -> dict[str, object] | None:
        return _try_http_admin("get_jobs", job_args, port)

    app = ServerWatchApp(
        fetch=fetch,
        port=port,
        interval=3600.0,
        watch_mode="jobs",
    )
    async with app.run_test(size=(220, 50), notifications=True) as pilot:
        for _ in range(100):
            await pilot.pause()
            if app._last_refresh is not None or app._last_error is not None:
                break
        assert app._last_refresh is not None or app._last_error is not None
        painted = "\n".join(
            strip.text.replace("\u2800", " ")
            for strip in app.screen._compositor.render_strips()
        )
        return app._quiesce, painted, app._last_error


@pytest.mark.asyncio
async def test_jobs_tui_renders_production_quiesce_controller_evidence(
    tmp_path: Path,
) -> None:
    """TUI presents controller state without translating it into permission.

    Mutation: remove the quiesce payload capture in ``_apply_result``. The
    direct transport still succeeds, but the retained canonical block and all
    three operator-visible controller facts disappear.
    """
    status_dir = tmp_path / "status"
    with (
        managed_env(
            **{
                EnvVar.STATUS_DIR.value: str(status_dir),
                EnvVar.LOCAL_ONLY.value: "true",
            }
        ),
        _production_routes(status_dir) as port,
    ):
        from ..serviceclient._transport import _try_http_admin

        pause = _try_http_admin("pause_service", {}, port)
        assert pause is not None and pause["ok"] is True, pause
        quiesce, painted, fetch_error = await _paint_quiesce_jobs_tui(
            port=port,
            job_args={},
        )

    from ..jobs import mapping

    canonical = mapping(quiesce)
    assert set(canonical) == QUIESCE_ENVELOPE_FIELDS
    assert canonical["state"] == "quiesced"
    assert canonical["vram_released"] is True
    assert canonical["safe_to_borrow_gpu"] is True
    assert fetch_error is None
    assert "quiesce quiesced" in painted
    assert "vram released" in painted
    assert "borrower safety safe" in painted


@pytest.mark.asyncio
async def test_jobs_tui_shows_quiesce_unavailable_after_a_route_error(
    tmp_path: Path,
) -> None:
    """A rejected production jobs request cannot render borrower safety."""
    status_dir = tmp_path / "status"
    with (
        managed_env(
            **{
                EnvVar.STATUS_DIR.value: str(status_dir),
                EnvVar.LOCAL_ONLY.value: "true",
            }
        ),
        _production_routes(status_dir) as port,
    ):
        retained, painted, fetch_error = await _paint_quiesce_jobs_tui(
            port=port,
            job_args={"controllable": "not-a-boolean"},
        )

    assert retained is None
    assert fetch_error == "controllable must be true or false when provided."
    assert "quiesce unavailable" in painted
    assert "borrower safety safe" not in painted
