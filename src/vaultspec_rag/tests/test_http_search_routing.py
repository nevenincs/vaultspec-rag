"""Unit tests for admin-tool URL routing in _http_search (no mocks)."""

from __future__ import annotations

import pytest

from ..cli._http_search import _logs_route_path

pytestmark = [pytest.mark.unit]


class TestLogsRoutePath:
    """get_logs must target /logs/json (JSON body), not plaintext /logs."""

    def test_routes_to_json_endpoint(self) -> None:
        assert _logs_route_path({}) == "/logs/json"

    def test_appends_lines_query(self) -> None:
        path = _logs_route_path({"lines": 50})
        assert path == "/logs/json?lines=50"
        assert path != "/logs" and not path.startswith("/logs?")

    def test_appends_filter_query(self) -> None:
        path = _logs_route_path(
            {"lines": 50, "job_id": "abc123", "contains": "Qdrant ready"}
        )
        assert path.startswith("/logs/json?")
        assert "lines=50" in path
        assert "job_id=abc123" in path
        assert "contains=Qdrant+ready" in path
