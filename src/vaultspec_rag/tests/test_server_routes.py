"""test server: the routes half."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from ..config._settings import reset_config
from ..config._types import EnvVar
from ..server import (
    ProjectRootRequiredError,
    ServerRouteRuntime,
    create_http_app,
)
from ..server._utils import (
    _default_root,
    _resolve_root,
)
from ..service import ServiceRegistry
from .test_server import (
    _run,
)

if TYPE_CHECKING:
    import httpx
    from starlette.applications import Starlette

pytestmark = [pytest.mark.unit]


class TestRouteMissingProjectRoot:
    """Routes return HTTP 400 (not 500) when project_root is absent in HTTP mode.

    The Starlette TestClient drives the route handlers synchronously.
    Module state (``_http_mode``) is set for the duration of each test and
    restored in ``finally`` blocks.  No GPU,
    no Qdrant, no model loading - the validation fires before any
    model/store access.

    The app-scoped runtime carries the known token used by the bearer header,
    so the handler proceeds to the root-validation guard.
    """

    _TOKEN = "test-token-s07"

    def _make_app(self) -> Starlette:
        return create_http_app(
            ServerRouteRuntime(
                token=self._TOKEN,
                registry=ServiceRegistry(),
                port=8765,
            ),
            lifespan=None,
        )

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._TOKEN}"}

    def test_search_route_returns_400_without_project_root(self):
        from starlette.testclient import TestClient

        import vaultspec_rag.server as mod

        from ..server._state import search_activity_ledger

        app = self._make_app()
        orig_mode = mod._http_mode
        query = f"search-activity-missing-root-{uuid.uuid4().hex}"
        mod._http_mode = True
        try:
            client: httpx.Client = cast(
                "httpx.Client", TestClient(app, raise_server_exceptions=False)
            )
            resp: httpx.Response = client.post(
                "/search",
                json={"query": query},
                headers=self._auth_headers(),
            )
            assert resp.status_code == 400
            data: dict[str, object] = cast("dict[str, object]", resp.json())
            assert data["ok"] is False
            assert data["error"] == "bad_request"
            assert "project_root" in cast("str", data["message"])

            activity = search_activity_ledger().snapshot(include_query=True)
            records = [
                record for record in activity["recent"] if record.get("query") == query
            ]
            assert len(records) == 1
            assert records[0]["state"] == "terminal"
            assert records[0]["outcome"] == "validation_rejected"
            assert records[0]["status_code"] == 400
            assert records[0]["error_code"] == "bad_request"
            assert not [
                record for record in activity["active"] if record.get("query") == query
            ]
        finally:
            mod._http_mode = orig_mode

    def test_search_route_records_invalid_bodies_as_validation_rejections(self):
        """Malformed and non-object bodies finish once before search admission."""
        from starlette.testclient import TestClient

        import vaultspec_rag.server as mod

        from ..server._state import search_activity_ledger

        app = self._make_app()
        orig_mode = mod._http_mode
        mod._http_mode = True
        try:
            client: httpx.Client = cast(
                "httpx.Client", TestClient(app, raise_server_exceptions=False)
            )
            cases = (
                ("malformed", b'{"query":', "invalid_json"),
                ("non-object", b'["not", "an", "object"]', "bad_request"),
            )
            for label, body, error_code in cases:
                before_snapshot = search_activity_ledger().snapshot(include_query=True)
                before = {
                    str(record["request_id"])
                    for group in (
                        before_snapshot["active"],
                        before_snapshot["recent"],
                    )
                    for record in group
                }
                response: httpx.Response = client.post(
                    "/search",
                    content=body,
                    headers={
                        **self._auth_headers(),
                        "Content-Type": "application/json",
                    },
                )

                assert response.status_code == 400, label
                data: dict[str, object] = cast("dict[str, object]", response.json())
                assert data["error"] == "bad_request", label
                activity = search_activity_ledger().snapshot(include_query=True)
                records = [
                    record
                    for group in (activity["active"], activity["recent"])
                    for record in group
                    if str(record["request_id"]) not in before
                ]
                assert len(records) == 1, label
                assert records[0]["state"] == "terminal", label
                assert records[0]["outcome"] == "validation_rejected", label
                assert records[0]["error_code"] == error_code, label
                assert all(
                    str(record["request_id"]) != str(records[0]["request_id"])
                    for record in activity["active"]
                ), label
        finally:
            mod._http_mode = orig_mode

    def test_unauthenticated_search_activity_route_never_exposes_query(self):
        """The token gate rejects the in-memory query-review surface."""
        from starlette.testclient import TestClient

        from ..server._search_activity import (
            SearchActivityCompletion,
            SearchActivityStart,
        )
        from ..server._state import search_activity_ledger

        query = f"operator-only-query-{uuid.uuid4().hex}"
        request_id = f"operator-only-request-{uuid.uuid4().hex}"
        ledger = search_activity_ledger()
        ticket = ledger.start(
            SearchActivityStart(
                request_id=request_id,
                query=query,
                search_type="vault",
                root="Y:/workspace",
                top_k=5,
            )
        )
        try:
            client: httpx.Client = cast(
                "httpx.Client",
                TestClient(self._make_app(), raise_server_exceptions=False),
            )
            response: httpx.Response = client.get("/search-activity")

            assert response.status_code == 401
            data: dict[str, object] = cast("dict[str, object]", response.json())
            assert data["error"] == "unauthorized"
            assert query not in response.text
        finally:
            assert ledger.finish(
                ticket,
                completion=SearchActivityCompletion(outcome="success", status_code=200),
            )

    def test_full_activity_ledger_backpressures_then_reviews_the_request(self):
        """Capacity waits for a slot and still records the eventual response."""
        child = r"""
import json
import threading
import time

from starlette.testclient import TestClient

import vaultspec_rag.server as server
from vaultspec_rag.server import ServerRouteRuntime, create_http_app
from vaultspec_rag.server._search_activity import (
    DEFAULT_MAX_ACTIVE_SEARCHES,
    SearchActivityCompletion,
    SearchActivityStart,
)
from vaultspec_rag.service import ServiceRegistry
from vaultspec_rag.server._state import search_activity_ledger


token = "activity-capacity-route-token"
waiting_query = "wait for activity capacity before validation"
previous_mode = server._http_mode
server._http_mode = True
try:
    app = create_http_app(
        ServerRouteRuntime(token=token, registry=ServiceRegistry(), port=8765),
        lifespan=None,
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        baseline = client.post(
            "/search",
            json={"query": "ledger capacity must not control search admission"},
            headers={"Authorization": f"Bearer {token}"},
        )
        ledger = search_activity_ledger()
        held = [
            ledger.start(SearchActivityStart(
                request_id=f"activity-capacity-{index}",
                query=f"activity capacity {index}",
                search_type="vault",
                root=None,
                top_k=None,
            ))
            for index in range(DEFAULT_MAX_ACTIVE_SEARCHES)
        ]
        request_started = threading.Event()
        response: dict[str, object] = {}
        failure: list[str] = []

        def request_when_full() -> None:
            request_started.set()
            try:
                constrained = client.post(
                    "/search",
                    json={"query": waiting_query},
                    headers={"Authorization": f"Bearer {token}"},
                )
                response["status_code"] = constrained.status_code
                response["body"] = constrained.json()
            except Exception as exc:
                failure.append(repr(exc))

        waiter = threading.Thread(target=request_when_full)
        waiter.start()
        assert request_started.wait(timeout=1.0)
        time.sleep(0.1)
        pending_before_release = waiter.is_alive()
        assert pending_before_release
        assert ledger.finish(
            held.pop(),
            completion=SearchActivityCompletion(outcome="success", status_code=200),
        )
        waiter.join(timeout=5.0)
        assert not waiter.is_alive()
        assert not failure
        after = ledger.snapshot(include_query=True)
    print(
        "ACTIVITY_CAPACITY_RESULT="
        + json.dumps(
            {
                "baseline": {
                    "status_code": baseline.status_code,
                    "body": baseline.json(),
                },
                "pending_before_release": pending_before_release,
                "constrained": response,
                "counts": after["counts"],
                "terminal": [
                    record
                    for record in after["recent"]
                    if record.get("query") == waiting_query
                ],
                "remaining_active": len(held),
            }
        )
    )
finally:
    server._http_mode = previous_mode
"""
        completed = subprocess.run(
            [sys.executable, "-c", child],
            cwd=Path(__file__).resolve().parents[3],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        prefix = "ACTIVITY_CAPACITY_RESULT="
        rendered = next(
            line.removeprefix(prefix)
            for line in completed.stdout.splitlines()
            if line.startswith(prefix)
        )
        result = cast("dict[str, object]", json.loads(rendered))
        assert result["pending_before_release"] is True
        constrained = cast("dict[str, object]", result["constrained"])
        assert constrained["status_code"] == 400
        assert constrained["status_code"] != 429
        counts = cast("dict[str, int]", result["counts"])
        assert counts["active"] == result["remaining_active"]
        assert counts["total"] == counts["active"] + counts["recent"]
        terminal = cast("list[dict[str, object]]", result["terminal"])
        assert len(terminal) == 1
        assert terminal[0]["state"] == "terminal"
        assert terminal[0]["query"] == "wait for activity capacity before validation"
        assert terminal[0]["outcome"] == "validation_rejected"
        assert terminal[0]["status_code"] == 400

    def test_benchmark_route_returns_400_without_project_root(self):
        from starlette.testclient import TestClient

        import vaultspec_rag.server as mod

        app = self._make_app()
        orig_mode = mod._http_mode
        mod._http_mode = True
        try:
            client: httpx.Client = cast(
                "httpx.Client", TestClient(app, raise_server_exceptions=False)
            )
            resp: httpx.Response = client.post(
                "/benchmark",
                json={},
                headers=self._auth_headers(),
            )
            assert resp.status_code == 400
            data: dict[str, object] = cast("dict[str, object]", resp.json())
            assert data["ok"] is False
            assert data["error"] == "bad_request"
            assert "project_root" in cast("str", data["message"])
        finally:
            mod._http_mode = orig_mode

    def test_reindex_route_returns_400_without_project_root(self):
        from starlette.testclient import TestClient

        import vaultspec_rag.server as mod

        app = self._make_app()
        orig_mode = mod._http_mode
        mod._http_mode = True
        try:
            client: httpx.Client = cast(
                "httpx.Client", TestClient(app, raise_server_exceptions=False)
            )
            resp: httpx.Response = client.post(
                "/reindex",
                json={"type": "vault"},
                headers=self._auth_headers(),
            )
            assert resp.status_code == 400
            data: dict[str, object] = cast("dict[str, object]", resp.json())
            assert data["ok"] is False
            assert data["error"] == "invalid_job_spec"
            assert "project_root" in cast("str", data["message"])
        finally:
            mod._http_mode = orig_mode

    def test_service_state_route_returns_400_without_project_root(self):
        from starlette.testclient import TestClient

        import vaultspec_rag.server as mod

        app = self._make_app()
        orig_mode = mod._http_mode
        mod._http_mode = True
        try:
            client: httpx.Client = cast(
                "httpx.Client", TestClient(app, raise_server_exceptions=False)
            )
            resp: httpx.Response = client.get(
                "/service-state",
                headers=self._auth_headers(),
            )
            assert resp.status_code == 400
            data: dict[str, object] = cast("dict[str, object]", resp.json())
            assert data["ok"] is False
            assert data["error"] == "bad_request"
            assert "project_root" in cast("str", data["message"])
        finally:
            mod._http_mode = orig_mode

    def test_code_file_route_returns_400_without_project_root(self):
        from starlette.testclient import TestClient

        import vaultspec_rag.server as mod

        app = self._make_app()
        orig_mode = mod._http_mode
        mod._http_mode = True
        try:
            client: httpx.Client = cast(
                "httpx.Client", TestClient(app, raise_server_exceptions=False)
            )
            resp: httpx.Response = client.post(
                "/code-file",
                json={"path": "src/main.py"},
                headers=self._auth_headers(),
            )
            assert resp.status_code == 400
            data: dict[str, object] = cast("dict[str, object]", resp.json())
            assert data["ok"] is False
            assert data["error"] == "bad_request"
            assert "project_root" in cast("str", data["message"])
        finally:
            mod._http_mode = orig_mode

    def test_vault_document_route_returns_400_without_project_root(self):
        from starlette.testclient import TestClient

        import vaultspec_rag.server as mod

        app = self._make_app()
        orig_mode = mod._http_mode
        mod._http_mode = True
        try:
            client: httpx.Client = cast(
                "httpx.Client", TestClient(app, raise_server_exceptions=False)
            )
            resp: httpx.Response = client.post(
                "/vault-document",
                json={"doc_id": "adr/overview"},
                headers=self._auth_headers(),
            )
            assert resp.status_code == 400
            data: dict[str, object] = cast("dict[str, object]", resp.json())
            assert data["ok"] is False
            assert data["error"] == "bad_request"
            assert "project_root" in cast("str", data["message"])
        finally:
            mod._http_mode = orig_mode


class TestHttpModeResolveRoot:
    """HTTP mode requires explicit project_root - no env/cwd fallback."""

    def test_default_root_raises_in_http_mode(self):
        import vaultspec_rag.server as mod

        orig = mod._http_mode
        mod._http_mode = True
        try:
            with pytest.raises(ValueError, match="project_root is required"):
                _default_root()
        finally:
            mod._http_mode = orig

    def test_resolve_root_none_raises_in_http_mode(self):
        import vaultspec_rag.server as mod

        orig = mod._http_mode
        mod._http_mode = True
        try:
            with pytest.raises(ValueError, match="project_root is required"):
                _resolve_root(None)
        finally:
            mod._http_mode = orig

    def test_resolve_root_explicit_works_in_http_mode(self, tmp_path: Path) -> None:
        import vaultspec_rag.server as mod

        (tmp_path / ".vault").mkdir()
        orig = mod._http_mode
        mod._http_mode = True
        try:
            result = _resolve_root(str(tmp_path))
            assert result == tmp_path.resolve()
        finally:
            mod._http_mode = orig

    def test_resolve_root_env_ignored_in_http_mode(self, tmp_path: Path) -> None:
        """Even with VAULTSPEC_RAG_ROOT set, HTTP mode rejects None."""
        import vaultspec_rag.server as mod

        (tmp_path / ".vault").mkdir()
        orig_mode = mod._http_mode
        orig_env = os.environ.get(EnvVar.RAG_ROOT)
        mod._http_mode = True
        os.environ[EnvVar.RAG_ROOT] = str(tmp_path)
        try:
            with pytest.raises(ValueError, match="project_root is required"):
                _resolve_root(None)
        finally:
            mod._http_mode = orig_mode
            if orig_env is not None:
                os.environ[EnvVar.RAG_ROOT] = orig_env
            else:
                os.environ.pop(EnvVar.RAG_ROOT, None)

    def test_resolve_root_empty_string_raises(self):
        """Empty string project_root is rejected in both modes."""
        with pytest.raises(ValueError, match="must not be empty"):
            _resolve_root("")

    def test_resolve_root_whitespace_only_raises(self):
        with pytest.raises(ValueError, match="must not be empty"):
            _resolve_root("   ")

    def test_vault_document_requires_running_daemon(self, tmp_path: Path) -> None:
        """get_vault_document is a REST client; it errors when no service is up.

        The resource delegates to the daemon's ``/vault-document`` endpoint
        through the shared ``serviceclient``; with an empty status dir (no
        ``service.json``) that raises a clear service-not-running RuntimeError.
        """
        import os

        from ..mcp._resources import get_vault_document

        # Isolate both the status dir and the machine-global storage dir:
        # discovery resolves the machine-global pointer (anchored to the storage
        # dir) before the status-dir hint, so without the storage-dir isolation a
        # real service running on the host would be discovered and the
        # "not running" assertion would fail.
        keys = ("VAULTSPEC_RAG_STATUS_DIR", "VAULTSPEC_RAG_QDRANT_STORAGE_DIR")
        prev = {k: os.environ.get(k) for k in keys}
        os.environ["VAULTSPEC_RAG_STATUS_DIR"] = str(tmp_path)
        os.environ["VAULTSPEC_RAG_QDRANT_STORAGE_DIR"] = str(
            tmp_path / "qdrant-server" / "storage"
        )
        reset_config()
        try:
            with pytest.raises(RuntimeError, match="is not running"):
                _run(get_vault_document("adr/overview"))
        finally:
            for key, value in prev.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            reset_config()


class TestReindexPreprocessPreflight:
    """POST /reindex reports whether a root's preprocess hooks will run.

    The route returns ``queued`` before the background job runs, so a
    non-interactive client cannot otherwise tell whether the root's
    document-preprocessing hooks will fire. The
    response now carries a ``preprocess`` pre-flight object mirroring the
    ``server start`` operator notice.

    Each request runs in a child process with its own production configuration
    and a stopped dispatch manager. This exercises the real ASGI route and
    admission scan without mutating the pytest process or loading a model.
    """

    _CHILD_ROUTE = """
import json
import sys

from starlette.testclient import TestClient

import vaultspec_rag.jobs as jobs
import vaultspec_rag.server as server
from vaultspec_rag.server import (  # absolute-import-ok
    ServerRouteRuntime,
    create_http_app,
)
from vaultspec_rag.service import ServiceRegistry  # absolute-import-ok


token = "isolated-preflight-token"
jobs.reset()
jobs.get_job_manager().begin_shutdown()
server._http_mode = True
try:
    with TestClient(
        create_http_app(
            ServerRouteRuntime(token=token, registry=ServiceRegistry(), port=8765),
            lifespan=None,
        )
    ) as client:
        response = client.post(
            "/reindex",
            json={"type": "code", "project_root": sys.argv[1]},
            headers={"Authorization": f"Bearer {token}"},
        )
    print(
        "REINDEX_PREFLIGHT_RESULT="
        + json.dumps({"status_code": response.status_code, "body": response.json()})
    )
finally:
    jobs.reset()
"""

    @staticmethod
    def _write_config(root: Path) -> None:
        (root / ".vault").mkdir(parents=True)
        (root / ".vaultragpreprocess.toml").write_text(
            "version = 2\n\n[[rule]]\n"
            'pattern = "*.pdf"\n'
            'target = "document"\n'
            'extractor_version = "1.0.0"\n'
            'command = "extract {path}"\n'
            'on_error = "skip"\n',
            encoding="utf-8",
        )

    def _post_reindex(
        self, root: Path, *, preprocess_mode: str | None
    ) -> dict[str, object]:
        env = os.environ.copy()
        env[EnvVar.STATUS_DIR.value] = str(root.parent / "status")
        env[EnvVar.QDRANT_STORAGE_DIR.value] = str(root.parent / "qdrant" / "storage")
        env[EnvVar.INDEX_SUPPORT_PROFILE.value] = "embedded-local"
        env[EnvVar.WATCH_ENABLED.value] = "false"
        if preprocess_mode is None:
            env.pop(EnvVar.PREPROCESS.value, None)
        else:
            env[EnvVar.PREPROCESS.value] = preprocess_mode
        completed = subprocess.run(
            [sys.executable, "-c", self._CHILD_ROUTE, str(root)],
            cwd=Path(__file__).resolve().parents[3],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        prefix = "REINDEX_PREFLIGHT_RESULT="
        rendered = next(
            line.removeprefix(prefix)
            for line in completed.stdout.splitlines()
            if line.startswith(prefix)
        )
        result = cast("dict[str, object]", json.loads(rendered))
        assert result["status_code"] == 200
        return cast("dict[str, object]", result["body"])

    def test_reindex_reports_hooks_will_run_under_default_mode(
        self, tmp_path: Path
    ) -> None:
        root = tmp_path / "proj"
        self._write_config(root)
        data = self._post_reindex(root, preprocess_mode=None)
        assert data["status"] == "queued"
        pre = cast("dict[str, object]", data["preprocess"])
        assert pre["config_present"] is True
        assert pre["rule_count"] == 1
        assert pre["mode"] == "default"
        assert pre["hooks_will_run"] is True

    def test_reindex_reports_hooks_skipped_when_mode_off(self, tmp_path: Path) -> None:
        root = tmp_path / "proj"
        self._write_config(root)
        data = self._post_reindex(root, preprocess_mode="off")
        pre = cast("dict[str, object]", data["preprocess"])
        # The count is still reported (the config's own), but the kill switch
        # means hooks will not run.
        assert pre["config_present"] is True
        assert pre["rule_count"] == 1
        assert pre["mode"] == "off"
        assert pre["hooks_will_run"] is False

    def test_reindex_reports_no_config_present(self, tmp_path: Path) -> None:
        root = tmp_path / "proj"
        (root / ".vault").mkdir(parents=True)
        data = self._post_reindex(root, preprocess_mode=None)
        pre = cast("dict[str, object]", data["preprocess"])
        assert pre["config_present"] is False
        assert pre["rule_count"] == 0
        assert pre["hooks_will_run"] is False


class TestProjectRootRequiredError:
    """ProjectRootRequiredError raised by _default_root in HTTP mode.

    These tests verify the exception type contract without exercising
    the full route stack (no GPU/Qdrant required).  Route-level 400
    coverage (route returns 400, not 500) is exercised via the
    Starlette TestClient against the affected handlers below.
    """

    def test_is_subclass_of_value_error(self):
        """ProjectRootRequiredError must be a ValueError subtype."""
        assert issubclass(ProjectRootRequiredError, ValueError)

    def test_default_root_raises_project_root_required_in_http_mode(self):
        import vaultspec_rag.server as mod

        orig = mod._http_mode
        mod._http_mode = True
        try:
            with pytest.raises(
                ProjectRootRequiredError, match="project_root is required"
            ):
                _default_root()
        finally:
            mod._http_mode = orig

    def test_resolve_root_none_raises_project_root_required_in_http_mode(self):
        import vaultspec_rag.server as mod

        orig = mod._http_mode
        mod._http_mode = True
        try:
            with pytest.raises(
                ProjectRootRequiredError, match="project_root is required"
            ):
                _resolve_root(None)
        finally:
            mod._http_mode = orig

    def test_project_root_required_error_message_actionable(self):
        """Error message must name the missing field."""
        import vaultspec_rag.server as mod

        orig = mod._http_mode
        mod._http_mode = True
        try:
            with pytest.raises(ProjectRootRequiredError) as exc_info:
                _resolve_root(None)
            assert "project_root" in str(exc_info.value)
        finally:
            mod._http_mode = orig


class TestRegistryFullErrorShape:
    """MCP tool handlers translate RegistryFullError into a structured dict."""

    def test_error_dict_shape(self) -> None:
        """_registry_full_error_dict contains every expected key."""
        from ..server import (
            _registry,
            _registry_full_error_dict,
        )
        from ..service import RegistryFullError

        exc = RegistryFullError(_registry.max_projects)
        result = _registry_full_error_dict(exc, _registry)
        assert result["ok"] is False
        assert result["error"] == "registry_full"
        assert result["max_projects"] == _registry.max_projects
        assert isinstance(result["busy_projects"], list)
        assert result["message"]  # non-empty message

    def test_local_store_locked_error_dict_shape(self, tmp_path: Path) -> None:
        """Local Qdrant lock contention returns an actionable MCP payload."""
        from .._store_locks import VaultStoreLockedError
        from ..server import _local_store_locked_error_dict

        db_path: Path = tmp_path / ".vault" / "data" / "search-data" / "qdrant"
        exc = VaultStoreLockedError(str(db_path))
        result = _local_store_locked_error_dict(exc)

        assert result["ok"] is False
        assert result["error"] == "local_store_locked"
        assert result["db_path"] == str(db_path)
        caps = result["backend_capabilities"]
        assert caps["backend"] == "qdrant-local"
        assert caps["concurrent_search_supported"] is True
        assert caps["same_project_search_strategy"] == "serialized"
        assert caps["cross_project_search_strategy"] == "parallel"
        assert caps["local_storage_process_model"] == "exclusive"
        assert "resident vaultspec-rag service" in result["message"]

    def test_ensure_watcher_uses_its_explicit_registry_for_peek_project(self) -> None:
        """_ensure_watcher must not bump ref_count on the slot.

        Reads the module source directly so the assertion is robust to
        whether the watcher task is running.
        """
        import inspect

        from ..server import _watcher as watcher_lifecycle

        source = inspect.getsource(watcher_lifecycle._warm_and_publish_watcher)
        assert "registry.peek_project" in source
        assert "_m._registry" not in source
        assert "registry.get_project" not in source
