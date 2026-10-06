"""Browser boundary and protected discovery over the production route app."""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

import pytest
from starlette.testclient import TestClient

from .._atomic_write import JsonWriteOptions, write_json_atomically
from ..server import ServerRouteRuntime, create_http_app
from ..service import ServiceRegistry
from ..serviceclient._discovery import _merge_service_status, _replace_service_status
from ..serviceclient._transport import _do_http_call, _try_http_health
from ._private_files import assert_private_file
from ._production_service import SERVICE_TOKEN, production_service, publish_discovery

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = [pytest.mark.unit, pytest.mark.usefixtures("isolated_status_dir")]

_TOKEN = "loopback-boundary-test-credential"


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_http_app(
        ServerRouteRuntime(token=_TOKEN, registry=ServiceRegistry(), port=8765),
        lifespan=None,
    )
    with TestClient(app, base_url="http://127.0.0.1:8765") as http:
        yield http


def test_public_health_omits_the_credential(client: TestClient) -> None:
    # Unconditional token serialization failed this assertion; restoration passed.
    response = client.get("/health")
    assert response.status_code == 200
    assert "service_token" not in response.json()
    assert _TOKEN not in response.text
    assert response.json()["port"] == 8765
    assert client.get("/jobs").status_code == 401


@pytest.mark.parametrize(
    "headers,query",
    [({"Authorization": f"Bearer {_TOKEN}"}, ""), ({}, f"?token={_TOKEN}")],
)
def test_existing_authenticated_identity_remains(
    client: TestClient, headers: dict[str, str], query: str
) -> None:
    response = client.get(f"/health{query}", headers=headers)
    assert response.status_code == 200
    assert response.json()["service_token"] == _TOKEN
    assert client.get(f"/jobs{query}", headers=headers).status_code == 200


def test_wrong_health_credential_is_an_explicit_refusal(client: TestClient) -> None:
    # Removing the credential refusal returned 200; restoration passed.
    response = client.get("/health", headers={"Authorization": "Bearer wrong-token"})
    assert response.status_code == 401
    assert response.json()["error"] == "unauthorized"
    assert "service_token" not in response.json()


@pytest.mark.parametrize(
    "host",
    [
        "attacker.invalid:8765",
        "localhost.attacker.invalid",
        "testserver",
        "foo.localhost",
        "127.0.0.1.attacker.invalid",
        "127.1",
        "2130706433",
        "0x7f000001",
        "0177.0.0.1",
        "127.00.0.1",
        "192.168.1.1",
        "localhost.",
        "localhost@attacker.invalid",
        "127.0.0.1:0",
        "127.0.0.1:65536",
        "[::1%25lo]:8765",
        "[::ffff:127.0.0.1]",
        "localhost:8765/path",
        " localhost:8765",
        "",
    ],
)
@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/health"),
        ("HEAD", "/health"),
        ("GET", "/jobs/"),
        ("POST", "/pause"),
        ("OPTIONS", "/unknown"),
    ],
)
def test_untrusted_host_is_rejected_before_routing(
    client: TestClient, host: str, method: str, path: str
) -> None:
    # Bypassing the Host rejection returned 200; restoration passed.
    response = client.request(
        method, path, headers={"Host": host, "Authorization": f"Bearer {_TOKEN}"}
    )
    assert response.status_code == 403
    if method != "HEAD":
        assert response.json()["error"] == "invalid_host"


@pytest.mark.parametrize(
    "origin",
    [
        "http://attacker.invalid:8765",
        "null",
        "",
        "http://127.0.0.1:8766",
        "https://127.0.0.1:8765",
        "http://localhost:8765",
        "http://user@127.0.0.1:8765",
        "http://127.0.0.1:8765/",
        "http://127.0.0.1:8765?",
        "http://127.0.0.1:8765#",
        "http://127.0.0.1:8765?q=x",
        "http://127.0.0.1:8765#fragment",
        "http://127.0.0.1:8765 http://attacker.invalid",
        "http://127.0.0.1:8765,http://attacker.invalid",
        " http://127.0.0.1:8765",
        "http://127.0.0.1:8765\t",
        "http://127.0.0.1:8765\n",
        "http://127.0.0.1:8765\\",
    ],
)
@pytest.mark.parametrize("method,path", [("GET", "/health"), ("POST", "/pause")])
def test_untrusted_origin_is_rejected_even_with_a_valid_token(
    client: TestClient, origin: str, method: str, path: str
) -> None:
    # Bypassing Origin matching returned 200; restoration passed.
    response = client.request(
        method, path, headers={"Origin": origin, "Authorization": f"Bearer {_TOKEN}"}
    )
    assert response.status_code == 403
    assert response.json()["error"] == "invalid_origin"


@pytest.mark.parametrize("name", ["Host", "Origin"])
@pytest.mark.parametrize("reverse", [False, True])
def test_duplicate_authorities_are_rejected(
    client: TestClient, name: str, reverse: bool
) -> None:
    # Accepting the first Host/Origin returned 200; restoration passed.
    values = (
        ["127.0.0.1:8765", "attacker.invalid:8765"]
        if name == "Host"
        else ["http://127.0.0.1:8765", "http://attacker.invalid:8765"]
    )
    if reverse:
        values.reverse()
    response = client.get("/health", headers=[(name, value) for value in values])
    assert response.status_code == 403
    assert response.json()["error"] == f"invalid_{name.lower()}"


@pytest.mark.parametrize(
    "authority", ["127.0.0.1:8765", "127.0.0.2", "localhost", "[::1]:8765"]
)
def test_loopback_same_origin_and_native_clients_remain_usable(
    client: TestClient, authority: str
) -> None:
    response = client.get(
        "/jobs",
        headers={
            "Host": authority,
            "Origin": f"http://{authority}",
            "Authorization": f"Bearer {_TOKEN}",
            "X-Forwarded-Host": "attacker.invalid",
        },
    )
    assert response.status_code == 200


def test_wire_clients_use_only_matching_discovery(isolated_status_dir: Path) -> None:
    # Removing port matching disclosed the token; restoration passed.
    # Ignoring a 401 accepted this Python PID as the service; restoration passed.
    with production_service(isolated_status_dir) as service:
        health = _try_http_health(service.port)
        assert health is not None and health["service_token"] == SERVICE_TOKEN
        jobs = _do_http_call(service.port, "/jobs", None)
        assert jobs is not None and "jobs" in jobs
        _replace_service_status(
            {"pid": os.getpid(), "port": service.port, "token": SERVICE_TOKEN}
        )
        legacy_health = _try_http_health(service.port)
        assert (
            legacy_health is not None
            and legacy_health["service_token"] == SERVICE_TOKEN
        )
        legacy_jobs = _do_http_call(service.port, "/jobs", None)
        assert legacy_jobs is not None and "jobs" in legacy_jobs
        _replace_service_status(
            {
                "pid": os.getpid(),
                "port": service.port,
                "service_token": "obsolete-token",
            }
        )
        assert _try_http_health(service.port) == {"status": "error", "http_code": 401}
        from ..cli._process import _is_our_service
        from ..cli._status_render import (
            _compute_token_match,
            _status_response_token_match,
        )

        assert not _is_our_service(
            os.getpid(), port=service.port, expected_token="obsolete-token"
        )
        assert _compute_token_match("obsolete-token", True, True, service.port) is False
        # Ignoring health refusals returned unknown token matches; restoration passed.
        assert (
            _status_response_token_match(
                "obsolete-token", {"status": "error", "http_code": 401}
            )
            is False
        )
        _replace_service_status(
            {
                "pid": os.getpid(),
                "port": service.port + 1,
                "service_token": SERVICE_TOKEN,
            }
        )
        public = _try_http_health(service.port)
        assert public is not None and "service_token" not in public
        rejected = _do_http_call(service.port, "/jobs", None)
        assert rejected is not None and rejected["error"] == "unauthorized"
        publish_discovery(isolated_status_dir, port=service.port)
        restored = _do_http_call(service.port, "/jobs", None)
        assert restored is not None and "jobs" in restored


def test_private_json_replacement_protects_existing_public_files(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "private-publication"
    directory.mkdir()
    path = directory / "discovery.json"
    path.write_text("public", encoding="utf-8")
    write_json_atomically(
        path, {"service_token": _TOKEN}, JsonWriteOptions(private=True)
    )
    assert json.loads(path.read_text(encoding="utf-8")) == {"service_token": _TOKEN}
    assert_private_file(path)
    assert list(directory.iterdir()) == [path]


def test_both_discovery_publications_are_private(isolated_status_dir: Path) -> None:
    from .._machine_lock import (
        acquire_machine_lock_lease,
        machine_discovery_path,
        publish_machine_discovery,
        release_machine_lock_lease,
    )

    payload = {"pid": os.getpid(), "port": 8765, "service_token": _TOKEN}
    _merge_service_status(payload)
    assert_private_file(isolated_status_dir / "service.json")
    _replace_service_status(payload)
    assert_private_file(isolated_status_dir / "service.json")
    lease, _ = acquire_machine_lock_lease()
    assert lease is not None
    try:
        publish_machine_discovery(lease, payload)
        assert_private_file(machine_discovery_path())
    finally:
        release_machine_lock_lease(lease)
