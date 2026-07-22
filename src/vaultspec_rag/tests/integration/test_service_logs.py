"""Real-file and authenticated HTTP coverage for managed log retrieval."""

from __future__ import annotations

import json
import os
import socket
import threading
import time
from typing import TYPE_CHECKING, cast

import pytest
import uvicorn
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient
from typer.testing import CliRunner

import vaultspec_rag.server as _m

from ...cli import app
from ...config import EnvVar, reset_config
from ...logging_config import (
    MANAGED_LOG_TRUNCATION_MARKER,
    MAX_MANAGED_LOG_SOURCE_BYTES,
)
from ...server._routes import ROUTES
from ...serviceclient._transport import (
    MAX_SERVICE_RESPONSE_BYTES,
    _logs_route_path,
    _try_http_admin,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path
    from typing import Protocol

    import httpx
    from starlette.requests import Request

    class HTTPTestClient(Protocol):
        def get(
            self,
            url: str,
            *,
            params: dict[str, str] | None = None,
            headers: dict[str, str] | None = None,
        ) -> httpx.Response: ...

        def close(self) -> None: ...


pytestmark = [pytest.mark.integration]
runner = CliRunner()


@pytest.fixture
def managed_log_app(
    tmp_path: Path,
) -> Iterator[tuple[HTTPTestClient, str, Path]]:
    """Serve the production routes against an isolated real log directory."""
    token = "managed-log-test-token"
    previous_token = _m._SERVICE_TOKEN
    previous_status_dir = os.environ.get(EnvVar.STATUS_DIR.value)
    _m._SERVICE_TOKEN = token
    os.environ[EnvVar.STATUS_DIR.value] = str(tmp_path)
    reset_config()
    client = cast("HTTPTestClient", TestClient(Starlette(routes=ROUTES)))
    try:
        yield client, token, tmp_path
    finally:
        client.close()
        _m._SERVICE_TOKEN = previous_token
        if previous_status_dir is None:
            os.environ.pop(EnvVar.STATUS_DIR.value, None)
        else:
            os.environ[EnvVar.STATUS_DIR.value] = previous_status_dir
        reset_config()


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _seed_grouped_logs(status_dir: Path) -> None:
    (status_dir / "service.log.3").write_text(
        "service-oldest\nservice-job job_id=abc123 keep\n",
        encoding="utf-8",
    )
    (status_dir / "service.log.1").write_text(
        "service-newer\n",
        encoding="utf-8",
    )
    (status_dir / "service.log").write_text(
        "service-active-a\nservice-active-b\n",
        encoding="utf-8",
    )
    (status_dir / "qdrant.log.4").write_text(
        "qdrant-oldest\nqdrant-job job_id=abc123 keep\n",
        encoding="utf-8",
    )
    (status_dir / "qdrant.log.2").write_text(
        "qdrant-newer\n",
        encoding="utf-8",
    )
    (status_dir / "qdrant.log").write_text(
        "qdrant-active-a\nqdrant-active-b\n",
        encoding="utf-8",
    )


@pytest.mark.parametrize("path", ["/logs", "/logs/json"])
def test_managed_log_routes_require_token(
    managed_log_app: tuple[HTTPTestClient, str, Path],
    path: str,
) -> None:
    client, _token, _status_dir = managed_log_app

    response = client.get(path)

    assert response.status_code == 401
    assert response.json() == {
        "ok": False,
        "error": "unauthorized",
        "message": (
            "This monitoring route requires the service_token via "
            "'Authorization: Bearer <token>' or '?token='."
        ),
    }


def test_logs_json_defaults_to_bounded_source_groups(
    managed_log_app: tuple[HTTPTestClient, str, Path],
) -> None:
    client, token, status_dir = managed_log_app
    _seed_grouped_logs(status_dir)

    response = client.get("/logs/json", params={"lines": "2"}, headers=_auth(token))

    assert response.status_code == 200
    assert response.json() == {
        "source": "all",
        "limit": 2,
        "groups": [
            {
                "source": "service",
                "lines": ["service-active-a", "service-active-b"],
            },
            {
                "source": "qdrant",
                "lines": ["qdrant-active-a", "qdrant-active-b"],
            },
        ],
        "filters": {},
    }


def test_logs_json_selects_one_source(
    managed_log_app: tuple[HTTPTestClient, str, Path],
) -> None:
    client, token, status_dir = managed_log_app
    _seed_grouped_logs(status_dir)

    response = client.get(
        "/logs/json",
        params={"source": "qdrant", "lines": "3"},
        headers=_auth(token),
    )

    assert response.status_code == 200
    assert response.json() == {
        "source": "qdrant",
        "limit": 3,
        "groups": [
            {
                "source": "qdrant",
                "lines": ["qdrant-newer", "qdrant-active-a", "qdrant-active-b"],
            }
        ],
        "filters": {},
    }


def test_logs_plaintext_labels_groups_without_merging(
    managed_log_app: tuple[HTTPTestClient, str, Path],
) -> None:
    client, token, status_dir = managed_log_app
    _seed_grouped_logs(status_dir)

    response = client.get("/logs", params={"lines": "1"}, headers=_auth(token))

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.text == ("[service]\nservice-active-b\n[qdrant]\nqdrant-active-b")


def test_log_filters_search_bounded_history_then_tail_each_source(
    managed_log_app: tuple[HTTPTestClient, str, Path],
) -> None:
    client, token, status_dir = managed_log_app
    _seed_grouped_logs(status_dir)

    response = client.get(
        "/logs/json",
        params={"lines": "1", "job_id": "ABC123", "contains": "KEEP"},
        headers=_auth(token),
    )

    assert response.status_code == 200
    assert response.json() == {
        "source": "all",
        "limit": 1,
        "groups": [
            {
                "source": "service",
                "lines": ["service-job job_id=abc123 keep"],
            },
            {
                "source": "qdrant",
                "lines": ["qdrant-job job_id=abc123 keep"],
            },
        ],
        "filters": {"job_id": "ABC123", "contains": "KEEP"},
    }


def test_empty_filtered_groups_are_successful(
    managed_log_app: tuple[HTTPTestClient, str, Path],
) -> None:
    client, token, status_dir = managed_log_app
    _seed_grouped_logs(status_dir)

    response = client.get(
        "/logs/json",
        params={"contains": "not-present"},
        headers=_auth(token),
    )

    assert response.status_code == 200
    assert response.json()["groups"] == [
        {"source": "service", "lines": []},
        {"source": "qdrant", "lines": []},
    ]


@pytest.mark.parametrize("path", ["/logs", "/logs/json"])
def test_logs_routes_reject_malformed_source_structurally(
    managed_log_app: tuple[HTTPTestClient, str, Path],
    path: str,
) -> None:
    client, token, _status_dir = managed_log_app

    response = client.get(
        path,
        params={"source": "database"},
        headers=_auth(token),
    )

    assert response.status_code == 400
    assert response.json() == {
        "ok": False,
        "error": "invalid_log_source",
        "message": "source must be one of service, qdrant, all.",
    }


def test_logs_route_clamps_each_source_to_maximum(
    managed_log_app: tuple[HTTPTestClient, str, Path],
) -> None:
    client, token, status_dir = managed_log_app
    record_count = 5_001
    (status_dir / "service.log").write_text(
        "".join(f"service-{index}\n" for index in range(record_count)),
        encoding="utf-8",
    )
    (status_dir / "qdrant.log").write_text(
        "".join(f"qdrant-{index}\n" for index in range(record_count)),
        encoding="utf-8",
    )

    response = client.get(
        "/logs/json", params={"lines": "999999"}, headers=_auth(token)
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["limit"] == 5_000
    groups = payload["groups"]
    assert len(groups[0]["lines"]) == 5_000
    assert len(groups[1]["lines"]) == 5_000
    assert groups[0]["lines"][0] == "service-1"
    assert groups[1]["lines"][0] == "qdrant-1"


def test_live_and_offline_cli_share_byte_truncation_contract(
    managed_log_app: tuple[HTTPTestClient, str, Path],
) -> None:
    client, token, status_dir = managed_log_app
    (status_dir / "service.log").write_bytes(b"x" * (MAX_MANAGED_LOG_SOURCE_BYTES * 3))

    live = client.get(
        "/logs/json",
        params={"source": "service", "lines": "1"},
        headers=_auth(token),
    )
    offline = runner.invoke(
        app,
        ["server", "logs", "--source", "service", "--limit", "1", "--json"],
    )

    assert live.status_code == 200
    assert offline.exit_code == 0, offline.output
    offline_payload = json.loads(offline.output)["data"]
    assert offline_payload == live.json()
    group = offline_payload["groups"][0]
    assert group["marker"] == MANAGED_LOG_TRUNCATION_MARKER
    assert group["truncation"]["scanned_bytes"] == MAX_MANAGED_LOG_SOURCE_BYTES
    assert group["truncation"]["returned_content_bytes"] <= MAX_MANAGED_LOG_SOURCE_BYTES


def test_logs_transport_path_carries_source_and_filters() -> None:
    path = _logs_route_path(
        {
            "lines": 25,
            "source": "qdrant",
            "job_id": "job 123",
            "contains": "disk full",
            "ignored": "value",
        }
    )

    assert path.startswith("/logs/json?")
    assert "lines=25" in path
    assert "source=qdrant" in path
    assert "job_id=job+123" in path
    assert "contains=disk+full" in path
    assert "ignored" not in path


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def _oversized_logs_response(_request: Request) -> JSONResponse:
    """Serve a real JSON body one byte beyond the transport's hard ceiling."""
    return JSONResponse({"blob": "x" * MAX_SERVICE_RESPONSE_BYTES})


def test_admin_transport_rejects_oversized_http_response_before_json_decode() -> None:
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(
            Starlette(routes=[Route("/logs/json", _oversized_logs_response)]),
            host="127.0.0.1",
            port=port,
            log_config=None,
            lifespan="off",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5.0
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.01)
    assert server.started
    try:
        result = _try_http_admin(
            "get_logs",
            {"source": "service", "lines": 1},
            port,
        )
    finally:
        server.should_exit = True
        thread.join(timeout=5.0)

    assert result is not None
    assert result["ok"] is False
    assert result["error"] == "http_call_failed"
    assert "ServiceResponseTooLargeError" in str(result["message"])


def test_admin_transport_preserves_live_structured_log_error(
    managed_log_app: tuple[HTTPTestClient, str, Path],
) -> None:
    _client, token, status_dir = managed_log_app
    port = _free_port()
    (status_dir / "service.json").write_text(
        json.dumps({"pid": os.getpid(), "port": port, "service_token": token}),
        encoding="utf-8",
    )
    server = uvicorn.Server(
        uvicorn.Config(
            Starlette(routes=ROUTES),
            host="127.0.0.1",
            port=port,
            log_config=None,
            lifespan="off",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5.0
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.01)
    assert server.started
    try:
        result = _try_http_admin(
            "get_logs",
            {"source": "database", "lines": 10},
            port,
        )
    finally:
        server.should_exit = True
        thread.join(timeout=5.0)

    assert result == {
        "ok": False,
        "error": "invalid_log_source",
        "message": "source must be one of service, qdrant, all.",
    }
