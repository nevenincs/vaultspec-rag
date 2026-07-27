"""Focused real-behavior coverage for the managed service jobs surface."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from ._service_jobs_route_helpers import (
    _assert_route_control_conflicts,
    _assert_route_creation_contract,
    _assert_route_exact_id_contract,
    _assert_route_paused_filter,
    _cancel_route_job,
    _create_route_job,
    _retry_delete_route_job,
)
from ._service_jobs_route_helpers import (
    _routes_app as _routes_app_fixture,
)
from ._service_jobs_support import _clean_jobs as _clean_jobs_fixture

__all__ = ["_clean_jobs_fixture", "_routes_app_fixture"]

if TYPE_CHECKING:
    from pathlib import Path

    import httpx
    from starlette.testclient import TestClient


@pytest.mark.unit
def test_jobs_route_canonical_control_retry_and_delete(
    _routes_app: tuple[TestClient, str],
    tmp_path: Path,
) -> None:
    (tmp_path / ".vault").mkdir()
    client, token = _routes_app
    headers = {"Authorization": f"Bearer {token}"}
    job_id = _assert_route_creation_contract(client, headers, tmp_path)
    _assert_route_exact_id_contract(client, headers, job_id)
    _assert_route_paused_filter(client, headers, job_id)

@pytest.mark.unit
def test_jobs_route_control_retry_and_terminal_delete(
    _routes_app: tuple[TestClient, str],
    tmp_path: Path,
) -> None:
    (tmp_path / ".vault").mkdir()
    client, token = _routes_app
    headers = {"Authorization": f"Bearer {token}"}
    created = _create_route_job(client, headers, tmp_path)
    assert created.status_code == 202
    job = created.json()["job"]
    job_id = str(job["id"])
    _assert_route_control_conflicts(client, headers, job_id)
    _cancel_route_job(client, headers, job_id, int(job["revision"]))
    _retry_delete_route_job(client, headers, job_id)

@pytest.mark.unit
def test_jobs_route_enforces_nonterminal_capacity(
    _routes_app: tuple[TestClient, str],
    tmp_path: Path,
) -> None:
    import os

    from ...config._settings import reset_config
    from ...config._types import EnvVar
    from ...jobs import reset

    client, token = _routes_app
    headers = {"Authorization": f"Bearer {token}"}
    roots = (tmp_path / "one", tmp_path / "two")
    for root in roots:
        (root / ".vault").mkdir(parents=True)
    prior = {
        EnvVar.STATUS_DIR: os.environ.get(EnvVar.STATUS_DIR),
        EnvVar.JOB_MAX_NONTERMINAL: os.environ.get(EnvVar.JOB_MAX_NONTERMINAL),
    }
    os.environ[EnvVar.STATUS_DIR] = str(tmp_path / "status")
    os.environ[EnvVar.JOB_MAX_NONTERMINAL] = "1"
    reset_config()
    reset()
    try:
        first = cast(
            "httpx.Response",
            client.post(  # pyright: ignore[reportUnknownMemberType]
                "/jobs",
                headers=headers,
                json={
                    "operation": "index",
                    "source": "vault",
                    "project_root": str(roots[0]),
                    "mode": "incremental",
                    "start_paused": True,
                },
            ),
        )
        assert first.status_code == 202
        second = cast(
            "httpx.Response",
            client.post(  # pyright: ignore[reportUnknownMemberType]
                "/jobs",
                headers=headers,
                json={
                    "operation": "index",
                    "source": "vault",
                    "project_root": str(roots[1]),
                    "mode": "incremental",
                    "start_paused": True,
                },
            ),
        )
        assert second.status_code == 429
        assert second.json()["code"] == "job_capacity_exceeded"
    finally:
        reset()
        for key, value in prior.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        reset_config()

@pytest.mark.unit
def test_reindex_route_rejects_unknown_type(
    _routes_app: tuple[TestClient, str],
    tmp_path: Path,
) -> None:
    client, token = _routes_app
    invalid_types: tuple[object, ...] = ("database", [])
    for invalid_type in invalid_types:
        response = cast(
            "httpx.Response",
            client.post(  # pyright: ignore[reportUnknownMemberType]
                "/reindex",
                headers={"Authorization": f"Bearer {token}"},
                json={"type": invalid_type, "project_root": str(tmp_path)},
            ),
        )
        assert response.status_code == 400
        assert response.json()["code"] == "invalid_job_spec"
