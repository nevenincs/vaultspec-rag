"""Search answers from a rebuild as it grows, and never from what it discarded.

A real service with real models rebuilds one source of a real root over its
own storage. The root first publishes a small corpus recognisable by an old
marker; the files are then replaced by a larger corpus carrying a fresh
marker and an explicit rebuild is submitted. Searches issued while the job is
still running must already return fresh content, never content carrying the
old marker, and must mark absence non-authoritative; a bounded freshness wait
must still wait for the rebuild to certify. A genuinely empty corpus answers
an authoritative empty result only once its rebuild has finished.
"""

from __future__ import annotations

import json
import shutil
import time
from typing import TYPE_CHECKING, cast

import pytest

from ...serviceclient._transport import _do_http_call
from .._scaffold import make_workspace
from ._service_search_diagnostics_support import (
    exact_job_snapshot,
    live_service_token,
    raw_search,
    wait_for_succeeded_job,
)
from .conftest import _live_service_context

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.subprocess_gpu]

_OLD = "obsoletemarkerkappa"
_FRESH = "freshmarkerzeta"
_FRESH_FILES = 600
_TERMINAL = {"succeeded", "done", "failed", "cancelled"}


def _write_corpus(root: Path, source: str, marker: str, count: int) -> None:
    if source == "vault":
        directory = root / ".vault" / "adr"
        shutil.rmtree(directory, ignore_errors=True)
        directory.mkdir(parents=True)
        for ordinal in range(count):
            (directory / f"note-{ordinal:04d}.md").write_text(
                "---\ntags: ['#adr', '#rebuild']\n---\n"
                f"# Note {ordinal}\n\n{marker} rebuild search note {ordinal}\n",
                encoding="utf-8",
            )
        return
    directory = root / "src"
    shutil.rmtree(directory, ignore_errors=True)
    directory.mkdir(parents=True)
    for ordinal in range(count):
        (directory / f"module_{ordinal:04d}.py").write_text(
            f'def {marker}_{ordinal}() -> str:\n    return "{marker} {ordinal}"\n',
            encoding="utf-8",
        )


def _rebuild(port: int, root: Path, source: str) -> str:
    response = _do_http_call(
        port,
        "/reindex",
        {
            "type": source,
            "clean": True,
            "authority": "rebuild",
            "project_root": str(root),
        },
        timeout=30,
    )
    assert isinstance(response, dict), response
    assert response.get("ok") is True, response
    return str(response["job_id"])


def _job_state(port: int, job_id: str) -> str:
    job = exact_job_snapshot(port, job_id)
    assert job is not None
    return str(job.get("state"))


def _search(
    port: int, token: str, root: Path, source: str, **policy: object
) -> tuple[int, dict[str, object]]:
    status, _headers, body = raw_search(
        port,
        token,
        {
            "query": f"{_FRESH} rebuild search",
            "type": source,
            "project_root": str(root),
            "top_k": 10,
            **policy,
        },
        timeout=120,
    )
    return status, body


def _source_fact(body: dict[str, object]) -> dict[str, object]:
    readiness = cast("dict[str, object]", body["readiness"])
    (fact,) = cast("list[dict[str, object]]", readiness["sources"])
    return fact


@pytest.mark.parametrize("source", ["vault", "code"])
def test_a_running_rebuild_serves_fresh_partial_results_and_nothing_old(
    tmp_path: Path, source: str
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    make_workspace(root)
    _write_corpus(root, source, _OLD, 3)
    with _live_service_context(tmp_path) as (port, _status_dir, _env):
        token = live_service_token(port)
        wait_for_succeeded_job(port, token, _rebuild(port, root, source))

        _write_corpus(root, source, _FRESH, _FRESH_FILES)
        job_id = _rebuild(port, root, source)

        partial: dict[str, object] | None = None
        reset_observed = False
        deadline = time.monotonic() + 300.0
        while partial is None and time.monotonic() < deadline:
            status, body = _search(port, token, root, source)
            still_running = _job_state(port, job_id) not in _TERMINAL
            served = json.dumps(body.get("results"))
            # An admitted rebuild discards nothing until its reset, so the old
            # index may answer until then. Fresh content exists only after the
            # reset, so once any is served nothing old may come back, and no
            # answer may mix the two.
            reset_observed = reset_observed or _FRESH in served
            if reset_observed:
                assert _OLD not in served, body
            if status == 200 and _FRESH in served and still_running:
                partial = body
            elif not still_running:
                break
        assert partial is not None, "no fresh result was served while indexing ran"
        assert _OLD not in json.dumps(partial["results"])
        assert _FRESH in json.dumps(partial["results"])
        fact = _source_fact(partial)
        assert fact["availability"] == "usable"
        assert fact["freshness"] == "updating"
        assert fact["absence_authority"] == "non_authoritative"

        bounded_status, bounded = _search(
            port,
            token,
            root,
            source,
            freshness_policy="bounded",
            freshness_wait_seconds=0.5,
        )
        if _job_state(port, job_id) not in _TERMINAL:
            # The certified target is the running rebuild's publication, so a
            # wait shorter than the rebuild times out rather than serving it.
            assert bounded_status == 503, bounded
            assert bounded["error"] == "freshness_wait_timeout"

        wait_for_succeeded_job(port, token, job_id)
        # Work queued behind the rebuild, such as an integrity reconcile of the
        # files it replaced, may still run after it; currency follows that work.
        settle_deadline = time.monotonic() + 120.0
        while True:
            status, done = _search(port, token, root, source)
            assert status == 200, done
            assert _OLD not in json.dumps(done["results"])
            if (
                _source_fact(done)["freshness"] == "current"
                or time.monotonic() >= settle_deadline
            ):
                break
            time.sleep(0.25)
        assert _source_fact(done)["freshness"] == "current"


def test_an_empty_corpus_is_authoritatively_empty_only_after_its_rebuild(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    make_workspace(root)
    with _live_service_context(tmp_path) as (port, _status_dir, _env):
        token = live_service_token(port)
        wait_for_succeeded_job(port, token, _rebuild(port, root, "vault"))

        status, body = _search(port, token, root, "vault")

        assert status == 200, body
        assert body["results"] == []
        assert _source_fact(body)["absence_authority"] == "authoritative"
