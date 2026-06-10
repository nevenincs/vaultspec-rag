"""Unit tests for service-lifecycle helper logic introduced in W02.P03.S05,
W02.P04.S09, and W02.P04.S10.

These tests exercise pure-logic helpers that do not require a live daemon,
a real port, or GPU models.  They redirect the status directory via
VAULTSPEC_RAG_STATUS_DIR (the project's designated isolation mechanism —
see the ``feedback_service_tests_isolate_STATUS_DIR`` memory note).
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

import pytest
import typer

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

from ..cli._service_lifecycle import (
    _orphan_probe_port,
    _render_orphan_status_json,
    _render_orphan_status_table,
)
from ..cli._service_status import _update_service_token
from ..config import EnvVar, reset_config

pytestmark = [pytest.mark.unit]


@pytest.fixture()
def isolated_status_dir(tmp_path: Path) -> Iterator[Path]:
    """Redirect the service status dir to *tmp_path* for the test duration."""
    prev = os.environ.get(EnvVar.STATUS_DIR.value)
    status_dir = tmp_path / "vaultspec-rag"
    status_dir.mkdir()
    os.environ[EnvVar.STATUS_DIR.value] = str(status_dir)
    reset_config()
    try:
        yield status_dir
    finally:
        if prev is None:
            os.environ.pop(EnvVar.STATUS_DIR.value, None)
        else:
            os.environ[EnvVar.STATUS_DIR.value] = prev
        reset_config()


# ---------------------------------------------------------------------------
# S09: orphan render helpers raise typer.Exit(code=4)
# ---------------------------------------------------------------------------


class TestOrphanRenderExitCodes:
    """Both orphan render helpers must raise typer.Exit(code=4) — S09 / #181 A1."""

    def test_render_orphan_json_exits_4(self) -> None:
        health: dict[str, object] = {"status": "ready"}
        with pytest.raises(typer.Exit) as exc_info:
            _render_orphan_status_json(8766, health)
        assert exc_info.value.exit_code == 4

    def test_render_orphan_table_exits_4(self) -> None:
        health: dict[str, object] = {"status": "ready"}
        with pytest.raises(typer.Exit) as exc_info:
            _render_orphan_status_table(8766, health)
        assert exc_info.value.exit_code == 4


# ---------------------------------------------------------------------------
# S09: _orphan_probe_port returns an int from config
# ---------------------------------------------------------------------------


class TestOrphanProbePort:
    """_orphan_probe_port must return the configured port as an int."""

    def test_returns_positive_int(self) -> None:
        port = _orphan_probe_port()
        assert isinstance(port, int)
        assert port > 0

    def test_respects_env_override(self) -> None:
        """VAULTSPEC_RAG_PORT is propagated through config into the helper."""
        prev = os.environ.get(EnvVar.PORT.value)
        os.environ[EnvVar.PORT.value] = "19991"
        reset_config()
        try:
            port = _orphan_probe_port()
            assert port == 19991
        finally:
            if prev is None:
                os.environ.pop(EnvVar.PORT.value, None)
            else:
                os.environ[EnvVar.PORT.value] = prev
            reset_config()


# ---------------------------------------------------------------------------
# S10: _update_service_token — atomic token persistence into service.json
# ---------------------------------------------------------------------------


class TestUpdateServiceToken:
    """_update_service_token persists the token from /health into service.json."""

    def _make_status_file(self, status_dir: Path, data: dict[str, object]) -> Path:
        sf = status_dir / "service.json"
        sf.write_text(json.dumps(data), encoding="utf-8")
        return sf

    def test_writes_token_into_existing_file(self, isolated_status_dir: Path) -> None:
        """Token is merged into service.json, preserving all existing fields."""
        self._make_status_file(isolated_status_dir, {"pid": 12345, "port": 8766})

        _update_service_token("tok-abc123")

        sf = isolated_status_dir / "service.json"
        result = json.loads(sf.read_text(encoding="utf-8"))
        assert result["service_token"] == "tok-abc123"
        assert result["pid"] == 12345
        assert result["port"] == 8766

    def test_noop_when_file_absent(self, isolated_status_dir: Path) -> None:
        """Helper is silent (no exception, no file created) when absent."""
        sf = isolated_status_dir / "service.json"
        assert not sf.exists()

        _update_service_token("tok-xyz")

        assert not sf.exists()

    def test_noop_when_token_already_matches(self, isolated_status_dir: Path) -> None:
        """No disk write occurs when the stored token equals the incoming token."""
        sf = self._make_status_file(
            isolated_status_dir,
            {"pid": 1, "port": 8766, "service_token": "tok-same"},
        )
        mtime_before = sf.stat().st_mtime_ns

        _update_service_token("tok-same")

        assert sf.stat().st_mtime_ns == mtime_before

    def test_overwrites_stale_token(self, isolated_status_dir: Path) -> None:
        """An outdated token in service.json is replaced with the fresh one."""
        self._make_status_file(
            isolated_status_dir,
            {"pid": 1, "port": 8766, "service_token": "old-token"},
        )

        _update_service_token("new-token")

        sf = isolated_status_dir / "service.json"
        result = json.loads(sf.read_text(encoding="utf-8"))
        assert result["service_token"] == "new-token"

    def test_write_is_atomic_tmp_file_cleaned_up(
        self, isolated_status_dir: Path
    ) -> None:
        """No .tmp artefact left after a successful write."""
        self._make_status_file(isolated_status_dir, {"pid": 1, "port": 8766})

        _update_service_token("tok-clean")

        tmp = isolated_status_dir / "service.tmp"
        assert not tmp.exists()
