"""The integrated reset, search and recovery contract across all three domains.

A real model-bearing service rebuilds real roots. Each root first publishes a
small corpus carrying an old marker, then its files are replaced by a larger
corpus carrying a fresh marker and an explicit rebuild is submitted. For code,
vault and documents alike:

- searches issued while the rebuild runs already return fresh content, never
  old content, with absence non-authoritative;
- a paused rebuild keeps serving its partial new index, and the route, the
  command line and an MCP process report the same readiness for it;
- a cancelled rebuild keeps its partial new points, and a new explicit
  rebuild resets the source again rather than continuing the cancelled one;
- searches of the rebuilding source and of its siblings keep answering while
  every domain rebuilds at once, and every domain still completes.

Latency and throughput figures are printed for the record; nothing here
asserts a speedup.
"""

from __future__ import annotations

import asyncio
import json
import shlex
import statistics
import sys
import textwrap
import threading
import time
from typing import TYPE_CHECKING, cast

import pytest
from typer.testing import CliRunner

from ..._source_types import PublicSourceType
from ...cli import app
from ...indexer._rebuild_lifecycle import capture_reset_epoch
from ...job_models import DesiredJobState
from ...serviceclient._transport import _do_http_call, _try_http_set_job_desired_state
from ...store_runtime import configured_backend_identity
from .._preprocess_approval import approve_preprocess_policy
from .._scaffold import make_workspace
from ._service_search_diagnostics_support import (
    exact_job_snapshot,
    live_service_token,
    raw_search,
    wait_for_succeeded_job,
)
from .conftest import _live_service_context
from .test_service_search_diagnostics_mcp import _official_search_call

if TYPE_CHECKING:
    from pathlib import Path

# Each test spawns a service that loads its own models, so the file belongs in
# the separate subprocess GPU invocation rather than beside the resident tier.
pytestmark = [pytest.mark.subprocess_gpu, pytest.mark.timeout(1800)]

_OLD = "obsoletemarkeromicron"
_FRESH = "freshmarkersigma"
_NEXT = "nextmarkertau"
_SOURCES = ("vault", "code", "document")
_FRESH_COUNT = {"vault": 400, "code": 400, "document": 80}
_TERMINAL = {"succeeded", "done", "failed", "cancelled", "interrupted"}
_MCP_TOOL = {
    "vault": "search_vault",
    "code": "search_codebase",
    "document": "search_documents",
}
_FACT_FIELDS = ("availability", "freshness", "absence_authority")

runner = CliRunner()


def _write_document_hook(root: Path) -> None:
    """Route ``docs/*.blob`` to the document domain through an approved hook."""
    extractor = root / "extract.py"
    extractor.write_text(
        textwrap.dedent("""
            import json, pathlib, sys
            path = sys.argv[1]
            text = pathlib.Path(path).read_text(encoding="utf-8")
            print(json.dumps({
                "schema_version": 1,
                "preprocessor_id": "rebuild.blob",
                "preprocessor_version": "1",
                "source_path": path,
                "units": [{"text": text}],
            }))
        """),
        encoding="utf-8",
    )
    command = f"{shlex.quote(sys.executable)} {shlex.quote(str(extractor))} {{path}}"
    (root / ".vaultragpreprocess.toml").write_text(
        "version = 2\n\n"
        '[[rule]]\npattern = "docs/*.blob"\n'
        f"command = '''{command}'''\n"
        'target = "document"\nextractor_version = "1"\non_error = "fail"\n',
        encoding="utf-8",
    )
    approve_preprocess_policy(root)


def _write_corpus(root: Path, source: str, marker: str, count: int) -> None:
    """Replace *source*'s files under *root* with *count* files naming *marker*."""
    import shutil

    if source == "vault":
        directory = root / ".vault" / "adr"
        name, body = (
            "note-{:04d}.md",
            (
                "---\ntags: ['#adr', '#rebuild']\n---\n# Note {n}\n\n"
                "{marker} rebuild contract note {n}\n"
            ),
        )
    elif source == "code":
        directory = root / "src"
        name = "module_{:04d}.py"
        body = (
            'def {marker}_{n}() -> str:\n    return "{marker} rebuild contract {n}"\n'
        )
    else:
        directory = root / "docs"
        name, body = "manual-{:04d}.blob", "{marker} rebuild contract manual {n}\n"
    shutil.rmtree(directory, ignore_errors=True)
    directory.mkdir(parents=True)
    for ordinal in range(count):
        (directory / name.format(ordinal)).write_text(
            body.format(marker=marker, n=ordinal), encoding="utf-8"
        )


def _project(tmp_path: Path) -> Path:
    root = make_workspace(tmp_path / "project")
    _write_document_hook(root)
    for source in _SOURCES:
        _write_corpus(root, source, _OLD, 3)
    return root


def _rebuild(port: int, root: Path, source: str) -> dict[str, object]:
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
    return response


def _rebuild_job(port: int, root: Path, source: str) -> str:
    return str(_rebuild(port, root, source)["job_id"])


def _job_state(port: int, job_id: str) -> str:
    job = exact_job_snapshot(port, job_id)
    assert job is not None, job_id
    return str(job.get("state"))


def _wait_for_state(port: int, job_id: str, wanted: str) -> None:
    deadline = time.monotonic() + 300.0
    state = ""
    while time.monotonic() < deadline:
        state = _job_state(port, job_id)
        if state == wanted:
            return
        assert state not in _TERMINAL - {wanted}, (job_id, state)
        time.sleep(0.1)
    pytest.fail(f"job {job_id} never reached {wanted}; last state {state}")


def _control(port: int, job_id: str, state: DesiredJobState) -> None:
    response = _try_http_set_job_desired_state(job_id, state, port, timeout=30)
    assert isinstance(response, dict), response
    assert response.get("ok") is not False, response


def _query(source: str, marker: str) -> str:
    return f"{marker} rebuild contract {source}"


def _search(
    port: int, token: str, root: Path, source: str, marker: str = _FRESH
) -> tuple[int, dict[str, object]]:
    status, _headers, body = raw_search(
        port,
        token,
        {
            "query": _query(source, marker),
            "type": source,
            "project_root": str(root),
            "top_k": 10,
        },
        timeout=120,
    )
    return status, body


def _fact(body: dict[str, object]) -> dict[str, object]:
    readiness = cast("dict[str, object]", body["readiness"])
    (fact,) = cast("list[dict[str, object]]", readiness["sources"])
    return fact


def _wait_for_partial(
    port: int, token: str, root: Path, source: str, job_id: str
) -> dict[str, object]:
    """Search until the running rebuild serves fresh content, and return it."""
    deadline = time.monotonic() + 300.0
    while time.monotonic() < deadline:
        status, body = _search(port, token, root, source)
        results = body.get("results")
        assert _OLD not in json.dumps(results), body
        if status == 200 and results and _job_state(port, job_id) not in _TERMINAL:
            return body
        assert _job_state(port, job_id) not in _TERMINAL, (
            "the rebuild finished before any partial result was observed"
        )
        time.sleep(0.05)
    pytest.fail("no fresh result was served while the rebuild ran")


def _cli_search(port: int, root: Path, source: str) -> dict[str, object]:
    result = runner.invoke(
        app,
        [
            "--target",
            str(root),
            "search",
            _query(source, _FRESH),
            "--type",
            source,
            "--port",
            str(port),
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    return cast("dict[str, object]", json.loads(result.output))


def _mcp_search(
    port: int, status_dir: Path, root: Path, source: str
) -> dict[str, object]:
    call = asyncio.run(
        _official_search_call(
            port=port, status_dir=status_dir, root=root, tool_name=_MCP_TOOL[source]
        )
    )
    assert call.is_error is False, call
    return dict(cast("dict[str, object]", call.structured_content))


def _projected(body: dict[str, object]) -> dict[str, object]:
    fact = _fact(body)
    return {field: fact[field] for field in _FACT_FIELDS}


@pytest.mark.parametrize("source", _SOURCES)
def test_a_paused_rebuild_serves_its_partial_index_the_same_on_every_surface(
    tmp_path: Path, source: str
) -> None:
    root = _project(tmp_path)
    with _live_service_context(tmp_path) as (port, status_dir, _env):
        token = live_service_token(port)
        wait_for_succeeded_job(port, token, _rebuild_job(port, root, source))

        _write_corpus(root, source, _FRESH, _FRESH_COUNT[source])
        job_id = _rebuild_job(port, root, source)
        partial = _wait_for_partial(port, token, root, source, job_id)
        assert _FRESH in json.dumps(partial["results"])
        assert _projected(partial) == {
            "availability": "usable",
            "freshness": "updating",
            "absence_authority": "non_authoritative",
        }

        _control(port, job_id, DesiredJobState.PAUSED)
        _wait_for_state(port, job_id, "paused")
        status, paused = _search(port, token, root, source)
        assert status == 200, paused
        assert paused["results"], "a paused rebuild must keep serving"
        assert _OLD not in json.dumps(paused["results"])
        cli = _cli_search(port, root, source)
        mcp = _mcp_search(port, status_dir, root, source)
        assert _projected(paused)["absence_authority"] == "non_authoritative"
        assert _projected(cli) == _projected(paused)
        assert _projected(mcp) == _projected(paused)
        assert _OLD not in json.dumps(cli.get("results"))
        assert _OLD not in json.dumps(mcp.get("results"))

        _control(port, job_id, DesiredJobState.RUNNING)
        wait_for_succeeded_job(port, token, job_id)
        status, done = _search(port, token, root, source)
        assert status == 200, done
        assert _OLD not in json.dumps(done["results"])
        assert _fact(done)["freshness"] == "current"


@pytest.mark.parametrize("source", _SOURCES)
def test_a_cancelled_rebuild_keeps_its_points_and_a_new_rebuild_resets_again(
    tmp_path: Path, source: str
) -> None:
    root = _project(tmp_path)
    with _live_service_context(tmp_path) as (port, _status_dir, _env):
        token = live_service_token(port)
        wait_for_succeeded_job(port, token, _rebuild_job(port, root, source))

        _write_corpus(root, source, _FRESH, _FRESH_COUNT[source])
        job_id = _rebuild_job(port, root, source)
        _wait_for_partial(port, token, root, source, job_id)
        _control(port, job_id, DesiredJobState.CANCELLED)
        _wait_for_state(port, job_id, "cancelled")
        cancelled_epoch = capture_reset_epoch(
            root, PublicSourceType(source), configured_backend_identity(root)
        ).epoch

        status, kept = _search(port, token, root, source)
        assert status == 200, kept
        assert _FRESH in json.dumps(kept["results"]), "cancel kept no new points"
        assert _OLD not in json.dumps(kept["results"])
        assert _fact(kept)["absence_authority"] == "non_authoritative"

        _write_corpus(root, source, _NEXT, 3)
        wait_for_succeeded_job(port, token, _rebuild_job(port, root, source))
        assert (
            capture_reset_epoch(
                root, PublicSourceType(source), configured_backend_identity(root)
            ).epoch
            > cancelled_epoch
        ), "a new rebuild continued the cancelled one instead of resetting"
        status, rebuilt = _search(port, token, root, source, marker=_NEXT)
        assert status == 200, rebuilt
        assert _FRESH not in json.dumps(rebuilt["results"])
        assert _NEXT in json.dumps(rebuilt["results"])
        assert _fact(rebuilt)["freshness"] == "current"


def _percentile(samples: list[float], fraction: float) -> float:
    ordered = sorted(samples)
    return ordered[min(len(ordered) - 1, int(fraction * len(ordered)))]


def test_searches_keep_answering_while_every_domain_rebuilds(tmp_path: Path) -> None:
    root = _project(tmp_path)
    with _live_service_context(tmp_path) as (port, _status_dir, _env):
        token = live_service_token(port)
        seeded = _rebuild(port, root, "combined")
        for domain in cast("dict[str, dict[str, object]]", seeded["domains"]).values():
            wait_for_succeeded_job(port, token, str(domain["job_id"]))

        for source in _SOURCES:
            _write_corpus(root, source, _FRESH, _FRESH_COUNT[source])
        started = time.monotonic()
        response = _rebuild(port, root, "combined")
        jobs = {
            source: str(domain["job_id"])
            for source, domain in cast(
                "dict[str, dict[str, object]]", response["domains"]
            ).items()
        }
        stop = threading.Event()
        latencies: dict[str, list[float]] = {source: [] for source in _SOURCES}
        outcomes: list[tuple[str, int, str | None]] = []
        leaks: list[dict[str, object]] = []
        lock = threading.Lock()

        def searcher(source: str) -> None:
            while not stop.is_set():
                began = time.perf_counter()
                status, body = _search(port, token, root, source)
                elapsed = time.perf_counter() - began
                error = cast("str | None", body.get("error"))
                with lock:
                    latencies[source].append(elapsed)
                    outcomes.append((source, status, error))
                    if _OLD in json.dumps(body.get("results")):
                        leaks.append(body)

        threads = [
            threading.Thread(target=searcher, args=(source,), daemon=True)
            for source in (*_SOURCES, "code", "vault")
        ]
        for thread in threads:
            thread.start()
        try:
            for job_id in jobs.values():
                wait_for_succeeded_job(port, token, job_id)
        finally:
            stop.set()
            for thread in threads:
                thread.join(timeout=180)
        rebuild_seconds = time.monotonic() - started

        assert all(not thread.is_alive() for thread in threads)
        assert leaks == [], "a search returned content the reset discarded"
        # Only the bounded reset may refuse a search; nothing waits for or
        # fails behind the whole rebuild.
        refused = [item for item in outcomes if item[1] != 200]
        assert all(error == "index_transition" for _s, _c, error in refused), refused
        for source in _SOURCES:
            answered = [
                item for item in outcomes if item[0] == source and item[1] == 200
            ]
            assert answered, f"no {source} search answered while every domain rebuilt"
            samples = latencies[source]
            print(
                f"{source}: {len(samples)} searches during a {rebuild_seconds:.1f}s "
                f"rebuild, p50 {statistics.median(samples):.3f}s, "
                f"p95 {_percentile(samples, 0.95):.3f}s, "
                f"max {max(samples):.3f}s"
            )
        total_files = sum(_FRESH_COUNT.values())
        print(f"indexed {total_files} files in {rebuild_seconds:.1f}s")
