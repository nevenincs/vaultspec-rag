"""Filter, sort and page the canonical service operator lists."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from .. import jobs
from ..config._settings import get_config
from ..job_models import JobSource
from ..logging_config import query_managed_logs
from ..server._search_activity import (
    SearchActivityCompletion,
    SearchActivityFilters,
    SearchActivityLedger,
    SearchActivityStart,
)
from ..server._state import search_activity_ledger
from .integration._service_jobs_route_helpers import _routes_app as _routes_app_fixture
from .integration._service_jobs_support import _clean_jobs as _clean_jobs_fixture

if TYPE_CHECKING:
    from pathlib import Path

    from starlette.testclient import TestClient

__all__ = ["_clean_jobs_fixture", "_routes_app_fixture"]

pytestmark = pytest.mark.unit


def test_jobs_filter_and_sort_before_paging(
    _routes_app: tuple[TestClient, str],
) -> None:
    oldest = jobs.record_start(JobSource.CODE, "watcher", command="pagination-match")
    middle = jobs.record_start(JobSource.CODE, "watcher", command="pagination-match")
    jobs.record_start(JobSource.CODE, "watcher", command="pagination-match")
    jobs.record_start(JobSource.VAULT, "watcher", command="pagination-other")
    client, token = _routes_app
    response = client.get(
        "/jobs",
        params={
            "token": token,
            "query": "pagination-match",
            "source": "code",
            "sort": "created_at",
            "order": "asc",
            "offset": 1,
            "limit": 1,
        },
    )
    assert response.status_code == 200
    page = response.json()
    assert [record["id"] for record in page["jobs"]] == [middle]
    assert page["matched"] == 3
    assert page["returned"] == 1
    assert page["offset"] == 1 and page["has_more"] is True
    assert page["total"] >= 4
    response = client.get(
        "/jobs",
        params={
            "token": token,
            "query": "pagination-match",
            "sort": "created_at",
            "order": "desc",
            "offset": 1,
            "limit": 2,
        },
    )
    assert [record["id"] for record in response.json()["jobs"]] == [middle, oldest]
    assert response.json()["has_more"] is False


def test_jobs_empty_page_retains_matching_count(
    _routes_app: tuple[TestClient, str],
) -> None:
    jobs.record_start(JobSource.CODE, "watcher", command="empty-page-match")
    client, token = _routes_app
    response = client.get(
        "/jobs",
        params={
            "token": token,
            "query": "empty-page-match",
            "offset": 0,
            "limit": 0,
        },
    )
    page = response.json()
    assert page["jobs"] == []
    assert page["matched"] == 1 and page["returned"] == 0
    assert page["has_more"] is True


def test_jobs_route_bounds_page_size_and_negative_offset(
    _routes_app: tuple[TestClient, str],
) -> None:
    """Removing the page ceiling fails limit; allowing negative offsets fails
    returned. Each mutation failed its assertion and passed after restoration.
    """
    for _ in range(3):
        jobs.record_start(JobSource.CODE, "watcher", command="bounded-page-match")
    client, token = _routes_app
    response = client.get(
        "/jobs",
        params={
            "token": token,
            "query": "bounded-page-match",
            "offset": -1,
            "limit": 999999,
        },
    )
    page = response.json()
    assert page["limit"] == 5000
    assert page["returned"] == 3
    assert page["offset"] == 0


def test_activity_pages_across_lanes_after_sorting_and_filtering() -> None:
    ledger = SearchActivityLedger(max_active=3, max_recent=3)
    first = ledger.start(
        SearchActivityStart("first", "matching oldest", "code", "/alpha", 1)
    )
    ledger.finish(first, completion=SearchActivityCompletion("failed", 500))
    ledger.start(SearchActivityStart("middle", "matching active", "code", "/alpha", 1))
    last = ledger.start(
        SearchActivityStart("last", "matching newest", "code", "/alpha", 1)
    )
    ledger.finish(last, completion=SearchActivityCompletion("success", 200))
    ledger.start(SearchActivityStart("other", "unrelated", "vault", "/beta", 1))

    page = ledger.snapshot(
        include_query=True,
        filters=SearchActivityFilters(
            query="MATCHING",
            search_type="code",
            sort="started_at",
            order="desc",
            offset=1,
            limit=1,
        ),
    )
    assert [record["request_id"] for record in page["records"]] == ["middle"]
    assert page["records"] == page["active"]
    assert page["matched"] == 3 and page["returned"] == 1
    assert page["has_more"] is True
    failures = ledger.snapshot(
        include_query=True,
        filters=SearchActivityFilters(
            query="matching",
            outcome="failed",
            state="terminal",
            limit=1,
        ),
    )
    assert [record["request_id"] for record in failures["records"]] == ["first"]
    assert failures["matched"] == 1 and failures["has_more"] is False


def test_logs_filter_request_and_text_then_page_across_rotations(
    tmp_path: Path,
) -> None:
    """Removing the request token boundary fails the matched-count assertion;
    restoring it passes, so similarly prefixed request ids cannot leak in.
    """
    (tmp_path / "service.log.1").write_text(
        "request_id=req-1 matched-oldest\nrequest_id=req-10 matched-wrong\n",
        encoding="utf-8",
    )
    (tmp_path / "service.log").write_text(
        "request_id=req-1 matched-middle\nrequest_id=req-1 noise\n"
        "request_id=req-1 matched-newest\n",
        encoding="utf-8",
    )
    page = query_managed_logs(
        1,
        source="service",
        request_id="req-1",
        contains="MATCHED",
        offset=1,
        order="desc",
        status_dir=tmp_path,
    )
    assert page["filters"] == {"request_id": "req-1", "contains": "MATCHED"}
    assert page.get("offset") == 1 and page.get("order") == "desc"
    assert page["groups"][0]["lines"] == ["request_id=req-1 matched-middle"]
    assert page["groups"][0].get("matched") == 3
    assert page["groups"][0].get("returned") == 1
    assert page["groups"][0].get("has_more") is True
    older = query_managed_logs(
        2,
        source="service",
        request_id="req-1",
        contains="matched",
        offset=1,
        order="asc",
        status_dir=tmp_path,
    )
    assert older["groups"][0]["lines"] == [
        "request_id=req-1 matched-oldest",
        "request_id=req-1 matched-middle",
    ]
    assert older["groups"][0].get("has_more") is False


def test_list_routes_forward_activity_and_log_page_parameters(
    _routes_app: tuple[TestClient, str],
    isolated_status_dir: Path,
) -> None:
    client, token = _routes_app
    ledger = search_activity_ledger()
    ticket = ledger.start(
        SearchActivityStart(
            "pagination-route-request",
            "pagination route query",
            "code",
            "/page-route",
            1,
        )
    )
    try:
        response = client.get(
            "/search-activity",
            params={
                "token": token,
                "request_id": ticket.request_id,
                "query": "ROUTE QUERY",
                "state": "active",
                "sort": "query",
                "order": "asc",
                "limit": 1,
                "offset": 0,
            },
        )
        page = response.json()
        assert response.status_code == 200
        assert [record["request_id"] for record in page["records"]] == [
            ticket.request_id
        ]
        assert page["matched"] == 1 and page["sort"] == "query"
        assert page["order"] == "asc" and page["has_more"] is False
        (isolated_status_dir / get_config().log_file).write_text(
            f"request_id={ticket.request_id} match-old\n"
            f"request_id={ticket.request_id} match-new\n",
            encoding="utf-8",
        )
        response = client.get(
            "/logs/json",
            params={
                "token": token,
                "request_id": ticket.request_id,
                "contains": "match",
                "source": "service",
                "lines": 1,
                "offset": 1,
                "order": "desc",
            },
        )
        page = response.json()
        assert response.status_code == 200
        assert page["filters"] == {"request_id": ticket.request_id, "contains": "match"}
        assert page["groups"][0]["lines"] == [
            f"request_id={ticket.request_id} match-old"
        ]
        assert page["groups"][0]["matched"] == 2
        legacy = client.get(
            "/logs/json",
            params={
                "token": token,
                "source": "service",
                "lines": 1,
            },
        )
        assert legacy.json() == {
            "source": "service",
            "limit": 1,
            "filters": {},
            "groups": [
                {
                    "source": "service",
                    "lines": [
                        f"request_id={ticket.request_id} match-new",
                    ],
                }
            ],
        }
    finally:
        ledger.finish(ticket, completion=SearchActivityCompletion("success", 200))
