"""Migration results determine the CLI outcome without opening real stores.

Split by what each half actually needs. The reported envelope is a pure
function of the results, so it is driven directly through the renderer with no
substitution at all. The exit status is not: it is raised by the command, and
reaching that code for real means a live Qdrant server and populated
collections on both backends, which the unit tier has not got. Only those
tests go through the CLI, and only they carry the scripted stores.
"""

from __future__ import annotations

import contextlib
import io
import json
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from ..cli import _service_storage as storage_cli
from ..cli import app
from ..storage_migration import MigrateResult

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from typer.testing import Result

pytestmark = [pytest.mark.unit]


@pytest.fixture
def run_migration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Callable[..., Result]:
    """Exercise argument parsing and outcome handling with scripted stores."""
    monkeypatch.setattr("qdrant_client.QdrantClient", Mock())
    monkeypatch.setattr(
        storage_cli, "_resolve_server_url", Mock(return_value="http://unused.invalid")
    )
    monkeypatch.setattr(
        storage_cli, "_migrate_name_map", Mock(return_value={"source": "target"})
    )
    monkeypatch.setattr(
        storage_cli, "_local_store_path", Mock(return_value=tmp_path / "qdrant")
    )
    monkeypatch.setattr(storage_cli, "_carry_identity_on_migrate", Mock())
    monkeypatch.setattr(storage_cli, "_rekey_manifest_on_migrate", Mock())

    def run(results: list[MigrateResult], *options: str) -> Result:
        monkeypatch.setattr(
            "vaultspec_rag.storage_migration.migrate_collections",
            Mock(return_value=results),
        )
        return CliRunner().invoke(
            app,
            ["server", "storage", "migrate", str(tmp_path), "--to", "server", *options],
        )

    return run


def _render(results: list[MigrateResult], *, json_mode: bool, failed: bool) -> str:
    """Render an outcome through production, with nothing substituted.

    The envelope and the human lines are a pure function of the results, so
    they are asked of the renderer itself rather than reached through a command
    that would have to be given scripted stores first.
    """
    stream = io.StringIO()
    with contextlib.redirect_stdout(stream):
        storage_cli._render_migrate(results, json_mode, failed=failed)
    return stream.getvalue()


@pytest.mark.parametrize("mixed", [False, True])
@pytest.mark.parametrize("json_mode", [False, True])
def test_failed_collection_fails_the_command(
    run_migration: Callable[..., Result], *, mixed: bool, json_mode: bool
) -> None:
    """Failed copies must fail both reporting channels.

    Observed the original handler fail the exit-code assertion. Restoring
    unconditional JSON success with the corrected exit kept failed the ``ok``
    assertion. Both cases passed after restoring the corrected handler.
    """
    results = [MigrateResult("source", "target", "failed", 3, "count_mismatch:3!=4")]
    if mixed:
        results.insert(0, MigrateResult("other", "other_target", "migrated", 2))
    options = ["--yes", "--json"] if json_mode else ["--yes"]

    result = run_migration(results, *options)

    assert result.exit_code == 1, result.output

    rendered = _render(results, json_mode=json_mode, failed=True)
    if json_mode:
        lines = rendered.splitlines()
        assert len(lines) == 1
        envelope = json.loads(lines[0])
        assert envelope["ok"] is False
        assert envelope["error"] == "migrate_failed"
        assert envelope["message"]
        assert envelope["data"]["results"] == [
            {
                "source": item.source,
                "target": item.target,
                "status": item.status,
                "points": item.points,
                "reason": item.reason,
            }
            for item in results
        ]
    else:
        assert "failed" in rendered
        assert "count_mismatch:3!=4" in rendered


@pytest.mark.parametrize("status", ["migrated", "skipped", "would_migrate"])
def test_success_skip_and_explicit_preview_remain_successful(
    run_migration: Callable[..., Result], status: str
) -> None:
    options = ["--yes", "--json"]
    if status == "would_migrate":
        options.append("--dry-run")

    results = [MigrateResult("source", "target", status)]

    result = run_migration(results, *options)

    assert result.exit_code == 0, result.output

    envelope = json.loads(_render(results, json_mode=True, failed=False))
    assert envelope["ok"] is True
    assert "error" not in envelope
    assert envelope["data"]["results"][0]["status"] == status


def test_implicit_preview_with_work_still_requires_confirmation(
    run_migration: Callable[..., Result],
) -> None:
    result = run_migration([MigrateResult("source", "target", "would_migrate")])

    assert result.exit_code == 1, result.output
    assert "would_migrate" in result.stdout
