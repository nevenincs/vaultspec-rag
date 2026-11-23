"""An incremental index its published proof cannot parent is refused over HTTP.

A real server answers ``/reindex`` over loopback for a hook root whose
document source carries a real committed proof. Editing the hook's declared
input makes that proof stale, and the refusal reaches the HTTP client, the
CLI and the job list exactly as the service produced it.

MUTATION PROOF, each run in one uninterrupted sequence:

- Dropping ``full_reindex_required`` from ``job_outcome_status`` fails
  ``test_the_refusal_is_one_409_envelope_and_creates_no_job`` on its status
  assertion: the refusal answers 500.
- Building the ``AdmissionRefusedError`` without the refusal's payload fails
  the same test on its ``rebuild_command`` assertion.
- Dropping the positional-only marker from ``_emit_json_error_and_exit``
  fails ``test_the_cli_passes_the_refusal_through_unchanged`` on its
  one-envelope assertion: the forwarded ``code`` field collides with the
  exit code and no envelope is written.

Restoring each returns the module to green.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import TYPE_CHECKING, cast

import pytest
from typer.testing import CliRunner

from ...cli import app
from ...serviceclient._transport import _try_http_admin
from .._hook_publication import (
    edit_hook_script,
    publish_empty_document_proof,
    write_hook_root,
)
from .._scaffold import make_workspace
from .._state_fixtures import reset_registry
from ._service_jobs_support import _canonical_resilience_server

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

runner = CliRunner()

pytestmark = [pytest.mark.unit]


@pytest.fixture(name="served_root")
def _served_root(tmp_path: Path) -> Iterator[tuple[Path, int, str]]:
    reset_registry()
    try:
        with _canonical_resilience_server(tmp_path) as (port, token):
            root = (tmp_path / "project").resolve()
            root.mkdir()
            write_hook_root(make_workspace(root))
            publish_empty_document_proof(root)
            edit_hook_script(root)
            yield root, port, token
    finally:
        reset_registry()


def _post_reindex(port: int, token: str, root: Path) -> tuple[int, dict[str, object]]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/reindex",
        data=json.dumps(
            {
                "type": "document",
                "clean": False,
                "authority": "publication",
                "project_root": str(root),
                "initiator_kind": "cli",
            }
        ).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30.0) as response:
            return int(response.status), json.loads(response.read())
    except urllib.error.HTTPError as refused:
        return refused.code, json.loads(refused.read())


def _one_envelope(stdout: str) -> dict[str, object]:
    lines = [line for line in stdout.splitlines() if line.strip()]
    assert len(lines) == 1, stdout
    envelope = json.loads(lines[0])
    assert isinstance(envelope, dict)
    return cast("dict[str, object]", envelope)


def test_the_refusal_is_one_409_envelope_and_creates_no_job(
    served_root: tuple[Path, int, str],
) -> None:
    root, port, token = served_root

    status, body = _post_reindex(port, token, root)

    assert status == 409, body
    assert body["ok"] is False
    assert body["error"] == "full_reindex_required"
    command = str(body["rebuild_command"])
    assert command.endswith("index --rebuild --type document")
    assert str(root) in command
    assert body["identity_changes"] == ["content_identity"]
    assert body["remediation"] == [command]
    jobs = _try_http_admin("get_jobs", {}, port)
    assert jobs is not None
    assert jobs["jobs"] == []


def test_the_cli_passes_the_refusal_through_unchanged(
    served_root: tuple[Path, int, str],
) -> None:
    root, port, _token = served_root
    args = ["--target", str(root), "index", "--type", "document", "--port", str(port)]

    result = runner.invoke(app, [*args, "--json"])

    assert result.exit_code == 1, result.stdout
    envelope = _one_envelope(result.stdout)
    assert envelope["ok"] is False
    assert envelope["error"] == "full_reindex_required"
    assert str(envelope["rebuild_command"]).endswith("index --rebuild --type document")

    human = runner.invoke(app, args)
    assert human.exit_code == 1
    assert "Code: full_reindex_required" in human.stdout
    assert "Next actions:" in human.stdout
    # The console wraps the command wherever the project path leaves it room.
    assert "--rebuild --type document" in " ".join(human.stdout.split())
