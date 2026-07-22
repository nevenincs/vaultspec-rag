"""Real-server coverage for typed service job-control transport operations."""

from __future__ import annotations

import json
import os
import socket
import threading
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING, cast

import uvicorn
from starlette.applications import Starlette

import vaultspec_rag.server as _server_state

from ...config import EnvVar, reset_config
from ...jobs import get_job_manager
from ...jobs import reset as reset_jobs
from ...server._routes import ROUTES
from ...serviceclient import (
    _try_http_create_job,
    _try_http_delete_job,
    _try_http_get_job,
    _try_http_retry_job,
    _try_http_set_job_desired_state,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@contextmanager
def _real_job_control_server(tmp_path: Path) -> Iterator[int]:
    """Run the production route table over a real loopback HTTP socket."""
    status_dir = tmp_path / "status"
    port = _free_port()
    token = "real-job-control-token"
    prior_status_dir = os.environ.get(EnvVar.STATUS_DIR)
    prior_watch_enabled = os.environ.get(EnvVar.WATCH_ENABLED)
    prior_token = _server_state._SERVICE_TOKEN
    server: uvicorn.Server | None = None
    thread: threading.Thread | None = None
    stopped = True
    try:
        status_dir.mkdir()
        os.environ[EnvVar.STATUS_DIR] = str(status_dir)
        os.environ[EnvVar.WATCH_ENABLED] = "false"
        reset_config()
        reset_jobs()
        _server_state._SERVICE_TOKEN = token
        (status_dir / "service.json").write_text(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "port": port,
                    "service_token": token,
                }
            ),
            encoding="utf-8",
        )

        server = uvicorn.Server(
            uvicorn.Config(
                Starlette(routes=ROUTES),
                host="127.0.0.1",
                port=port,
                log_config=None,
                access_log=False,
                lifespan="off",
            )
        )
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        deadline = time.monotonic() + 5.0
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started
        yield port
    finally:
        if server is not None:
            server.should_exit = True
        if thread is not None:
            thread.join(timeout=5.0)
            stopped = not thread.is_alive()
        reset_jobs()
        _server_state._SERVICE_TOKEN = prior_token
        if prior_status_dir is None:
            os.environ.pop(EnvVar.STATUS_DIR, None)
        else:
            os.environ[EnvVar.STATUS_DIR] = prior_status_dir
        if prior_watch_enabled is None:
            os.environ.pop(EnvVar.WATCH_ENABLED, None)
        else:
            os.environ[EnvVar.WATCH_ENABLED] = prior_watch_enabled
        reset_config()
        assert stopped
def test_typed_job_control_transport_uses_real_http_methods_and_conflicts(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    (project_root / ".vault").mkdir(parents=True)

    with _real_job_control_server(tmp_path) as port:
        created = _try_http_create_job(
            "vault",
            str(project_root),
            port,
            start_paused=True,
            idempotency_key="real-transport-lifecycle",
            timeout=5.0,
        )
        assert created is not None
        assert created["ok"] is True
        assert created["status"] == "accepted"
        assert created["code"] == "job_created"
        created_job = cast("dict[str, object]", created["job"])
        job_id = cast("str", created_job["id"])
        revision = cast("int", created_job["revision"])
        assert created_job["state"] == "paused"

        detail = _try_http_get_job(job_id, port, timeout=5.0)
        assert detail is not None
        assert detail["ok"] is True
        detail_job = cast("dict[str, object]", detail["job"])
        assert detail_job["id"] == job_id
        assert detail_job["desired_state"] == "paused"

        force_rejected = _try_http_set_job_desired_state(
            job_id,
            "running",
            port,
            mode="force",
            timeout=5.0,
        )
        assert force_rejected is not None
        assert force_rejected["ok"] is False
        assert force_rejected["status"] == "error"
        assert force_rejected["error"] == "force_termination_unavailable"

        delete_rejected = _try_http_delete_job(job_id, port, timeout=5.0)
        assert delete_rejected is not None
        assert delete_rejected["ok"] is False
        assert delete_rejected["error"] == "job_not_terminal"

        cancelled = _try_http_set_job_desired_state(
            job_id,
            "cancelled",
            port,
            expected_revision=revision,
            timeout=5.0,
        )
        assert cancelled is not None
        assert cancelled["ok"] is True
        cancelled_job = cast("dict[str, object]", cancelled["job"])
        assert cancelled_job["state"] == "cancelled"

        get_job_manager().begin_shutdown()
        retried = _try_http_retry_job(job_id, port, timeout=5.0)
        assert retried is not None
        assert retried["ok"] is True
        assert retried["status"] == "accepted"
        assert retried["code"] == "job_retry_created"
        retried_job = cast("dict[str, object]", retried["job"])
        assert retried_job["parent_job_id"] == job_id
        assert retried_job["id"] != job_id

        deleted = _try_http_delete_job(job_id, port, timeout=5.0)
        assert deleted is not None
        assert deleted["ok"] is True
        assert deleted["code"] == "job_deleted"

        missing = _try_http_get_job(job_id, port, timeout=5.0)
        assert missing is not None
        assert missing["ok"] is False
        assert missing["error"] == "job_not_found"

