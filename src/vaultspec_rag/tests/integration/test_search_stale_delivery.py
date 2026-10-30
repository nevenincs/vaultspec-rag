"""Real stale-hit delivery preserves content and admits incremental repair."""

from __future__ import annotations

import atexit
import json
import os
import sys
import threading
import time
from typing import TYPE_CHECKING, Literal, cast

import pytest
from uvicorn.protocols.http.h11_impl import RequestResponseCycle

from ..._search_drift import SearchDriftAuditor
from ...indexer._run_ledger_models import RunAuthority
from ...serviceclient._transport import _do_http_call, _try_http_reindex
from .._child_signal import CHILD_PROCESS_TIMEOUT_SECONDS
from ._service_search_diagnostics_support import (
    live_service_token,
    raw_search,
    wait_for_succeeded_job,
)
from .conftest import _live_service_context

if TYPE_CHECKING:
    from pathlib import Path
    from types import FrameType


def install_delivery_observer(root: Path, report: Path) -> None:
    """Observe actual sends across the event-loop and background worker threads."""
    send_codes = {RequestResponseCycle.send.__code__}
    try:
        from uvicorn.protocols.http.httptools_impl import (
            RequestResponseCycle as HTTPToolsCycle,
        )
    except ImportError:
        pass
    else:
        send_codes.add(HTTPToolsCycle.send.__code__)
    watched = send_codes | {SearchDriftAuditor.note_served.__code__}
    previous_main = sys.getprofile()
    previous_thread = threading.getprofile()
    main_thread = threading.get_ident()
    lock = threading.Lock()
    sent_at: int | None = None
    request_id: str | None = None
    complete = False

    def restore() -> None:
        sys.setprofile(
            previous_main if threading.get_ident() == main_thread else previous_thread
        )
        threading.setprofile(previous_thread)

    atexit.register(restore)

    def observe(
        frame: FrameType,
        event: Literal["call", "return", "c_call", "c_return", "c_exception"],
        arg: object,
    ) -> None:
        nonlocal sent_at, request_id, complete
        if (
            not complete
            and frame.f_code not in watched
            and previous_main is None
            and previous_thread is None
        ):
            return
        previous = (
            previous_main if threading.get_ident() == main_thread else previous_thread
        )
        if previous is not None:
            previous(frame, event, arg)
        if complete:
            sys.setprofile(previous)
            return
        if frame.f_code not in watched:
            return
        if event == "return" and frame.f_code in send_codes:
            cycle = frame.f_locals.get("self")
            message = cast("dict[str, object] | None", frame.f_locals.get("message"))
            if not getattr(cycle, "response_complete", False) or not isinstance(
                message, dict
            ):
                return
            if message.get("type") != "http.response.body" or message.get(
                "more_body", False
            ):
                return
            body = message.get("body")
            if not isinstance(body, bytes) or b"stale_delivery_probe.py" not in body:
                return
            payload = json.loads(body)
            if any(
                row.get("freshness") == "stale" for row in payload.get("results", [])
            ):
                with lock:
                    sent_at = time.monotonic_ns()
                    request_id = payload.get("request_id")
        if (
            event == "call"
            and frame.f_code is SearchDriftAuditor.note_served.__code__
            and frame.f_locals.get("root") == root
        ):
            with lock:
                temporary = report.with_suffix(".tmp")
                temporary.write_text(
                    json.dumps(
                        {
                            "body_sent_at": sent_at,
                            "request_id": request_id,
                            "audit_noted_at": time.monotonic_ns(),
                        }
                    ),
                    encoding="utf-8",
                )
                temporary.replace(report)
                complete = True
            restore()

    sys.setprofile(observe)
    threading.setprofile(observe)


def _delivery_bootstrap(
    tmp_path: Path,
    root: Path,
    report: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bootstrap = tmp_path / "bootstrap"
    bootstrap.mkdir()
    (bootstrap / "sitecustomize.py").write_text(
        "import os, sys, traceback\nfrom pathlib import Path\n"
        "if any(sys.orig_argv[i:i+2] == ['-m', 'vaultspec_rag.server'] "
        "for i in range(len(sys.orig_argv)-1)):\n"
        "    try:\n"
        "        from vaultspec_rag.tests.integration.test_search_stale_delivery "
        "import install_delivery_observer\n"
        f"        install_delivery_observer(Path({str(root.resolve())!r}), "
        f"Path({str(report)!r}))\n"
        "    except BaseException:\n"
        "        traceback.print_exc()\n        os._exit(1)\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(
        "PYTHONPATH",
        os.pathsep.join((str(bootstrap), os.environ.get("PYTHONPATH", ""))),
    )


def _wait_for_integrity_repair(
    port: int,
    root: Path,
    deadline: float,
) -> dict[str, object]:
    listing: dict[str, object] | None = None
    repair: dict[str, object] | None = None
    while time.monotonic() < deadline:
        listing = _do_http_call(port, "/jobs?limit=128", None, timeout=5)
        assert isinstance(listing, dict), listing
        for candidate in cast("list[dict[str, object]]", listing["jobs"]):
            spec = cast("dict[str, object]", candidate["spec"])
            initiator = cast("dict[str, object]", candidate["initiator"])
            if (
                spec.get("project_root") == str(root.resolve())
                and initiator.get("kind") == "integrity"
            ):
                repair = candidate
        if repair is not None:
            break
        time.sleep(0.1)
    assert repair is not None, listing
    return repair


@pytest.mark.subprocess_gpu
def test_stale_delivery_precedes_incremental_repair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "project"
    (root / ".vault").mkdir(parents=True)
    source = root / "stale_delivery_probe.py"
    source.write_text(
        "def stale_delivery_probe(value: int) -> int:\n    return value + 12345\n",
        encoding="utf-8",
    )
    report = tmp_path / "delivery.json"
    _delivery_bootstrap(tmp_path, root, report, monkeypatch)
    with _live_service_context(tmp_path / "service") as (port, _, _):
        token = live_service_token(port)
        created = _try_http_reindex(
            "code",
            True,
            port,
            str(root),
            authority=RunAuthority.REBUILD,
            initiator_kind="cli",
        )
        assert isinstance(created, dict) and created.get("ok") is True, created
        job_id = created["job_id"]
        assert isinstance(job_id, str)
        wait_for_succeeded_job(port, token, job_id)
        source.write_text(
            "def stale_delivery_probe(value: int) -> int:\n    return value + 54321\n",
            encoding="utf-8",
        )
        status, _, response = raw_search(
            port,
            token,
            {
                "query": "stale_delivery_probe",
                "type": "combined",
                "project_root": str(root),
                "include_documents": False,
                "top_k": 5,
            },
            timeout=300,
        )
        assert status == 200, response
        rows = cast("list[dict[str, object]]", response["results"])
        hits = [row for row in rows if row.get("path") == source.name]
        assert hits and all(row["freshness"] == "stale" for row in hits), response
        assert all(
            "12345" in str(row["snippet"]) and "54321" not in str(row["snippet"])
            for row in hits
        )
        deadline = time.monotonic() + CHILD_PROCESS_TIMEOUT_SECONDS
        while not report.exists():
            assert time.monotonic() < deadline, (
                "audit never observed the delivered stale page"
            )
            time.sleep(0.05)
        observed = json.loads(report.read_text(encoding="utf-8"))
        assert observed["request_id"] == response["request_id"]
        sent_at = observed["body_sent_at"]
        assert isinstance(sent_at, int), observed
        assert 0 < sent_at <= observed["audit_noted_at"]
        repair = _wait_for_integrity_repair(port, root, deadline)
        spec = cast("dict[str, object]", repair["spec"])
        assert spec["mode"] == "incremental"
        assert spec["authority"] == RunAuthority.PUBLICATION.value
        repair_id = repair["id"]
        assert isinstance(repair_id, str)
        wait_for_succeeded_job(port, token, repair_id)
        status, _, current = raw_search(
            port,
            token,
            {
                "query": "stale_delivery_probe",
                "type": "code",
                "project_root": str(root),
            },
            timeout=300,
        )
        assert status == 200, current
        current_rows = cast("list[dict[str, object]]", current["results"])
        assert current_rows and all(
            row["freshness"] == "current" for row in current_rows
        )
