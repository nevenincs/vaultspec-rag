"""The service search route refuses document filters as the caller's error.

CPU-only: the refusal is decided before any count, model, or GPU work, so an
unindexed root answers it exactly as an indexed one would.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from starlette.testclient import TestClient

from ..server import ServerRouteRuntime, create_http_app
from ..service import ServiceRegistry

if TYPE_CHECKING:
    from pathlib import Path

    from httpx2 import Response

pytestmark = [pytest.mark.unit]

_TOKEN = "metadata-filter-token"


def _search(root: Path, body: dict[str, object]) -> Response:
    registry = ServiceRegistry()
    app = create_http_app(
        ServerRouteRuntime(token=_TOKEN, registry=registry, port=8765),
        lifespan=None,
    )
    with TestClient(
        app, raise_server_exceptions=False, base_url="http://127.0.0.1"
    ) as client:
        return client.post(
            "/search",
            headers={"Authorization": f"Bearer {_TOKEN}"},
            json={"query": "manual", "project_root": str(root), **body},
        )


@pytest.fixture
def declared_root(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    (root / ".vault").mkdir(parents=True)
    (root / ".vaultragpreprocess.toml").write_text(
        'version = 2\n[[filterable_metadata]]\nkey = "lang"\nscope = "unit"\n',
        encoding="utf-8",
    )
    return root


@pytest.mark.parametrize(
    "body",
    [
        {"type": "document", "metadata_filters": {"owner": ["me"]}},
        {
            "type": "combined",
            "include_documents": True,
            "metadata_filters": {"owner": ["me"]},
        },
        {"type": "document", "query": "manual meta.owner=me"},
    ],
)
def test_undeclared_metadata_key_is_a_400_naming_the_declared_keys(
    declared_root: Path, body: dict[str, object]
) -> None:
    # Guard. Proven to fail: removing the InvalidFilterForSearchTypeError
    # branch from _execute_search_route turns the refusal into a 500, failing
    # the status assertion below.
    response = _search(declared_root, body)
    assert response.status_code == 400
    payload = response.json()
    assert payload["ok"] is False
    assert payload["error"] == "unknown_filter_key"
    assert payload["offending"] == ["meta.owner"]
    assert "meta.lang" in payload["message"]


def test_locator_kind_outside_the_closed_set_is_a_400(declared_root: Path) -> None:
    response = _search(declared_root, {"type": "document", "locator_kind": "folio"})
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_filter_for_search_type"


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"extractor_prefix": 3}, "extractor_prefix must be a string"),
        ({"metadata_filters": ["lang"]}, "metadata_filters must map"),
    ],
)
def test_wrong_json_shape_is_a_400_before_the_search_runs(
    declared_root: Path, body: dict[str, object], message: str
) -> None:
    response = _search(declared_root, {"type": "document", **body})
    assert response.status_code == 400
    assert message in str(response.json())
