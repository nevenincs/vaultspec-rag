"""Canonical generation survey facts survive the real CLI JSON adapter."""

from __future__ import annotations

import json
import tempfile
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from .._store_models import (
    generation_code_collection,
    publish_served_code_collection,
    root_collection_prefix,
    served_code_pointer_path,
)
from ..cli import app
from ..config._types import EnvVar
from ..server._routes_storage import _shape_survey_payload, _SurveyPayloadRequest
from ..serviceclient import _transport
from ..storage_manifest import ManifestEntry
from ..storage_survey import classify_namespaces, is_temp_rooted
from ..store_schema import CODE_COLLECTION, DOCUMENT_COLLECTION, VAULT_COLLECTION
from .conftest import managed_env
from .test_generation_survey import _publish_code_proof
from .test_storage_ops import _identity

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


def _offline_transport(
    monkeypatch: pytest.MonkeyPatch, payload: dict[str, object]
) -> list[dict[str, object]]:
    calls: list[dict[str, object]] = []

    def fetch(
        command: str, arguments: dict[str, object], _port: int
    ) -> dict[str, object]:
        assert command == "get_storage_survey"
        calls.append(arguments.copy())
        return json.loads(json.dumps(payload))

    monkeypatch.setattr(_transport, "_try_http_admin", fetch)
    return calls


@pytest.mark.parametrize("condition", ["unattributed", "unreadable", "empty", "debt"])
def test_service_generation_facts_survive_full_cli_json_round_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, condition: str
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    prefix = root_collection_prefix(root)
    derived = f"{prefix}{CODE_COLLECTION}"
    served = f"{derived}_gserved"
    old = f"{derived}_gsuperseded"
    names = [served]
    manifest = {prefix: ManifestEntry(prefix=prefix, root=str(root), backend="server")}
    expected: tuple[str | None, list[str] | None] = (None, None)
    if condition == "unattributed":
        manifest = {}
    else:
        names.append(generation_code_collection(derived, _publish_code_proof(root)))
        publish_served_code_collection(root, served)
        if condition == "unreadable":
            served_code_pointer_path(root).write_text("{unreadable", encoding="utf-8")
        else:
            expected = (served, [])
        if condition == "debt":
            names.append(old)
            expected = (served, [old])
    surveys = classify_namespaces(names, manifest)
    payload = _shape_survey_payload(
        _SurveyPayloadRequest(
            surveys=surveys,
            status_filter=None,
            limit=200,
            root=None,
            computed_at="2026-10-03T00:00:00+00:00",
            source="cache",
        )
    )
    assert len(payload["namespaces"]) == 1
    wire_entry = payload["namespaces"][0]
    assert (
        wire_entry["served_code_collection"],
        wire_entry["unreferenced_generations"],
    ) == expected
    calls = _offline_transport(monkeypatch, payload)
    result = CliRunner().invoke(
        app, ["server", "storage", "survey", "--fresh", "--json"]
    )
    assert result.exit_code == 0, result.output
    envelope = json.loads(result.stdout)
    assert envelope["ok"] is True
    assert calls == [{"fresh": "true"}]
    [entry] = envelope["data"]["namespaces"]
    assert (
        entry["served_code_collection"],
        entry["unreferenced_generations"],
    ) == expected
    assert entry["prefix"] == wire_entry["prefix"]
    assert entry["root"] == wire_entry["root"]
    assert entry["status"] == wire_entry["status"]
    assert entry["collections"] == wire_entry["collections"]


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"served_code_collection": None, "unreferenced_generations": None},
        {"served_code_collection": "served", "unreferenced_generations": None},
        {"served_code_collection": None, "unreferenced_generations": []},
        {"served_code_collection": "served", "unreferenced_generations": [1]},
        {"served_code_collection": "", "unreferenced_generations": []},
    ],
)
def test_missing_or_incomplete_generation_evidence_remains_unknown_in_cli(
    monkeypatch: pytest.MonkeyPatch, fields: dict[str, object]
) -> None:
    payload: dict[str, object] = {
        "ok": True,
        "namespaces": [
            {
                "prefix": "r0123456789ab_",
                "root": "/project",
                "status": "live",
                "collections": [],
                **fields,
            }
        ],
    }
    _offline_transport(monkeypatch, payload)
    result = CliRunner().invoke(app, ["server", "storage", "survey", "--json"])
    assert result.exit_code == 0, result.output
    [entry] = json.loads(result.stdout)["data"]["namespaces"]
    assert entry["served_code_collection"] is None
    assert entry["unreferenced_generations"] is None


@pytest.mark.parametrize("mixed", [False, True])
@pytest.mark.parametrize("unverified", [False, True])
def test_stamped_models_and_per_kind_counts_survive_json_and_human_adapters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mixed: bool, unverified: bool
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    prefix = root_collection_prefix(root)
    vault, code, document = (
        f"{prefix}{kind}"
        for kind in (VAULT_COLLECTION, CODE_COLLECTION, DOCUMENT_COLLECTION)
    )
    identities = {
        vault: _identity(dense_model="archived/dense"),
        code: _identity(dense_model="replacement/dense" if mixed else "archived/dense"),
    }
    surveys = classify_namespaces(
        [vault, code, document],
        {
            prefix: ManifestEntry(
                prefix=prefix,
                root=str(root),
                backend="server",
                collection_identity=identities,
            )
        },
        point_counts={vault: 4, code: 7, document: None if unverified else 9},
    )
    payload = _shape_survey_payload(
        _SurveyPayloadRequest(
            surveys=surveys,
            status_filter=None,
            limit=200,
            root=None,
            computed_at="2026-10-03T00:00:00+00:00",
            source="cache",
        )
    )
    _offline_transport(monkeypatch, payload)
    result = CliRunner().invoke(app, ["server", "storage", "survey", "--json"])
    assert result.exit_code == 0, result.output
    [entry] = json.loads(result.stdout)["data"]["namespaces"]
    assert entry["models"] == {
        name: identity.dense_model for name, identity in identities.items()
    }
    assert document not in entry["models"], (
        "An unstamped collection gained a model label"
    )
    assert (entry["vault_points"], entry["code_points"], entry["document_points"]) == (
        4,
        7,
        0 if unverified else 9,
    )
    assert entry["points"] == (11 if unverified else 20)
    assert entry["points_verified"] is not unverified
    human = CliRunner().invoke(app, ["server", "storage", "survey"])
    assert human.exit_code == 0, human.output
    assert "predate model stamping" not in human.stdout
    assert (
        "mixed embedding models: archived/dense, replacement/dense" in human.stdout
    ) is mixed


@pytest.mark.parametrize(
    "models", [None, [], {"collection": 1}, {"known": "model", "bad": False}]
)
def test_malformed_published_model_map_remains_unknown(
    monkeypatch: pytest.MonkeyPatch, models: object
) -> None:
    _offline_transport(
        monkeypatch,
        {
            "ok": True,
            "namespaces": [
                {
                    "prefix": "r0123456789ab_",
                    "root": "/project",
                    "status": "live",
                    "models": models,
                }
            ],
        },
    )
    result = CliRunner().invoke(app, ["server", "storage", "survey", "--json"])
    assert result.exit_code == 0, result.output
    [entry] = json.loads(result.stdout)["data"]["namespaces"]
    assert entry["models"] == {}


@pytest.mark.parametrize("published", [True, False, None, "malformed"])
def test_temp_rooted_uses_the_published_fact_before_client_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, published: bool | str | None
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    prefix = root_collection_prefix(root)
    server_is_temp = published is True
    server_temp = root.parent if server_is_temp else tmp_path / "elsewhere"
    client_temp = tmp_path / "elsewhere" if server_is_temp else root.parent
    names = [f"{prefix}{CODE_COLLECTION}"]
    surveys = classify_namespaces(
        names, {prefix: ManifestEntry(prefix=prefix, root=str(root), backend="server")}
    )
    with managed_env(
        **{
            variable.value: str(server_temp)
            for variable in (EnvVar.TEMP, EnvVar.TMP, EnvVar.TMPDIR)
        }
    ):
        monkeypatch.setattr(tempfile, "tempdir", str(server_temp))
        payload = _shape_survey_payload(
            _SurveyPayloadRequest(
                surveys=surveys,
                status_filter=None,
                limit=200,
                root=None,
                computed_at="2026-10-03T00:00:00+00:00",
                source="cache",
            )
        )
    assert payload["namespaces"][0]["temp_rooted"] is server_is_temp
    if published is None:
        payload["namespaces"][0].pop("temp_rooted")
    elif isinstance(published, str):
        payload["namespaces"][0]["temp_rooted"] = published
    with managed_env(
        **{
            variable.value: str(client_temp)
            for variable in (EnvVar.TEMP, EnvVar.TMP, EnvVar.TMPDIR)
        }
    ):
        monkeypatch.setattr(tempfile, "tempdir", str(client_temp))
        local_is_temp = is_temp_rooted(str(root))
        assert local_is_temp is not server_is_temp
        expected = published if isinstance(published, bool) else local_is_temp
        _offline_transport(monkeypatch, payload)
        result = CliRunner().invoke(app, ["server", "storage", "survey", "--json"])
        assert result.exit_code == 0, result.output
        [entry] = json.loads(result.stdout)["data"]["namespaces"]
        assert entry["temp_rooted"] is expected
        human = CliRunner().invoke(app, ["server", "storage", "survey"])
        assert human.exit_code == 0, human.output
        assert ("[temp]" in human.stdout) is expected
        assert ("temp-rooted" in human.stdout) is expected
