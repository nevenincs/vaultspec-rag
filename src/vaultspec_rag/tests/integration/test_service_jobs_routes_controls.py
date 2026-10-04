"""Focused real-behavior coverage for the managed service jobs surface."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from ._service_jobs_route_helpers import (
    _assert_route_control_conflicts,
    _assert_route_exact_id_contract,
    _assert_route_paused_filter,
    _cancel_route_job,
    _retry_delete_route_job,
    _seed_paused_route_job,
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
    job_id = _seed_paused_route_job(tmp_path).id
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
    job = _seed_paused_route_job(tmp_path)
    job_id = job.id
    _assert_route_control_conflicts(client, headers, job_id)
    _cancel_route_job(client, headers, job_id, job.revision)
    _retry_delete_route_job(client, headers, job_id)


@pytest.mark.unit
def test_jobs_route_enforces_nonterminal_capacity(
    _routes_app: tuple[TestClient, str],
    tmp_path: Path,
) -> None:
    import os

    from ...config._types import EnvVar
    from ...jobs import get_job_manager, reset
    from .._config_fixtures import reset_config

    client, token = _routes_app
    headers = {"Authorization": f"Bearer {token}"}
    roots = (tmp_path / "one", tmp_path / "two")
    for root in roots:
        (root / ".vault").mkdir(parents=True)
    prior = {
        EnvVar.STATUS_DIR: os.environ.get(EnvVar.STATUS_DIR),
        EnvVar.JOB_MAX_NONTERMINAL: os.environ.get(EnvVar.JOB_MAX_NONTERMINAL),
        EnvVar.WATCH_ENABLED: os.environ.get(EnvVar.WATCH_ENABLED),
    }
    os.environ[EnvVar.STATUS_DIR] = str(tmp_path / "status")
    os.environ[EnvVar.JOB_MAX_NONTERMINAL] = "1"
    os.environ[EnvVar.WATCH_ENABLED] = "false"
    reset_config()
    reset()
    # Admission still persists while dispatch is stopped, so the first job
    # stays queued and occupies the only nonterminal slot without running.
    get_job_manager().begin_shutdown()
    try:
        first, second = (
            cast(
                "httpx.Response",
                client.post(
                    "/reindex",
                    headers=headers,
                    json={
                        "type": "vault",
                        "clean": False,
                        "authority": "publication",
                        "project_root": str(root),
                    },
                ),
            )
            for root in roots
        )
        assert first.status_code == 200, first.text
        assert second.status_code == 429, second.text
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
            client.post(
                "/reindex",
                headers={"Authorization": f"Bearer {token}"},
                json={"type": invalid_type, "project_root": str(tmp_path)},
            ),
        )
        assert response.status_code == 400
        assert response.json()["code"] == "invalid_job_spec"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("clean", "authority"),
    [
        (False, None),
        (True, None),
        (False, "rebuild"),
        (True, "publication"),
        (False, "audit_verification"),
        (True, "audit_verification"),
    ],
)
def test_reindex_route_requires_exact_explicit_authority(
    clean: bool,
    authority: str | None,
) -> None:
    """The adapter may validate consent but must never derive it from ``clean``."""
    from ...server._routes_reindex import _validated_reindex_authority

    payload: dict[str, object] = {"clean": clean}
    if authority is not None:
        payload["authority"] = authority

    with pytest.raises(ValueError, match="authority"):
        _validated_reindex_authority(payload, clean=clean)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("clean", "authority"),
    [(False, "publication"), (True, "rebuild")],
)
def test_reindex_route_accepts_only_matching_explicit_authority(
    clean: bool,
    authority: str,
) -> None:
    from ...indexer._run_ledger_models import RunAuthority
    from ...server._routes_reindex import _validated_reindex_authority

    assert _validated_reindex_authority(
        {"clean": clean, "authority": authority},
        clean=clean,
    ) is RunAuthority(authority)
