"""An unverifiable served pointer refuses a clean with one typed outcome.

A real server answers ``/clean`` over loopback against real local storage,
and the CLI runs ``clean`` in process exactly as an operator does. Each root
holds a served-collection pointer naming a collection the root does not own,
so which code collection it serves is not established and nothing may be
deleted.

MUTATION PROOF, each run in one uninterrupted sequence:

- Projecting the refusal in the clean route as the exception class name
  again (``type(exc).__name__``) fails
  ``test_the_clean_route_reports_the_typed_refusal`` on its ``error_kind``
  assertion.
- Removing the ``JobError`` branch from the CLI ``clean`` command lets the
  refusal escape with no envelope and fails
  ``test_cli_clean_projects_the_refusal_as_one_envelope`` on its one-line
  assertion (zero lines), and the human variant on its escaped-exception
  assertion.

Restoring each returns the module to green.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

import pytest
from typer.testing import CliRunner

from ..._store_models import served_code_pointer_path
from ...cli import app
from ...config._types import EnvVar
from ...serviceclient._transport import _try_http_clean
from .._scaffold import make_workspace
from .._state_fixtures import reset_registry
from ..conftest import managed_env
from ._service_jobs_support import _canonical_resilience_server

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

runner = CliRunner()

pytestmark = [pytest.mark.unit]

_KIND = "served_pointer_unverifiable"


def _poisoned_root(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    make_workspace(root)
    pointer = served_code_pointer_path(root)
    pointer.parent.mkdir(parents=True, exist_ok=True)
    # A vault collection name is never a code collection this root owns,
    # under either backend.
    pointer.write_text(json.dumps({"collection": "vault_docs"}), encoding="utf-8")
    return root


def _one_envelope(stdout: str) -> dict[str, object]:
    lines = [line for line in stdout.splitlines() if line.strip()]
    assert len(lines) == 1, stdout
    envelope = json.loads(lines[0])
    assert isinstance(envelope, dict)
    return cast("dict[str, object]", envelope)


@pytest.fixture(name="local_backend")
def _local_backend() -> Iterator[None]:
    with managed_env(**{EnvVar.QDRANT_URL.value: ""}):
        reset_registry()
        try:
            yield
        finally:
            reset_registry()


@pytest.mark.usefixtures("local_backend")
def test_the_clean_route_reports_the_typed_refusal(tmp_path: Path) -> None:
    root = _poisoned_root(tmp_path)
    with _canonical_resilience_server(tmp_path) as (port, _token):
        result = _try_http_clean("code", port, str(root))

    assert result is not None
    assert result["ok"] is False, result
    assert result["partial"] is False
    domains = cast("dict[str, dict[str, object]]", result["domains"])
    code = domains["code"]
    assert code["ok"] is False
    assert code["cleared"] == []
    assert code["error_kind"] == _KIND, code
    assert str(served_code_pointer_path(root)) in str(code["detail"])
    assert "nothing was deleted" in str(code["remediation"])
    assert served_code_pointer_path(root).exists()


@pytest.mark.usefixtures("local_backend")
def test_cli_clean_projects_the_refusal_as_one_envelope(tmp_path: Path) -> None:
    root = _poisoned_root(tmp_path)
    result = runner.invoke(
        app, ["--target", str(root), "clean", "code", "--yes", "--json"]
    )

    assert result.exit_code == 1, result.output
    envelope = _one_envelope(result.stdout)
    assert envelope["ok"] is False
    assert envelope["command"] == "clean"
    assert envelope["error"] == _KIND
    assert str(served_code_pointer_path(root)) in str(envelope["message"])
    assert envelope["clean_type"] == "code"
    remediation = cast("list[str]", envelope["remediation"])
    assert len(remediation) == 1
    assert "nothing was deleted" in remediation[0]
    assert served_code_pointer_path(root).exists()


@pytest.mark.usefixtures("local_backend")
def test_cli_clean_projects_the_refusal_in_human_mode(tmp_path: Path) -> None:
    root = _poisoned_root(tmp_path)
    result = runner.invoke(app, ["--target", str(root), "clean", "code", "--yes"])

    assert result.exit_code == 1, result.output
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert f"Code: {_KIND}" in result.output
    assert "Next actions:" in result.output
    assert "nothing was deleted" in result.output
    assert "Traceback" not in result.output
    assert served_code_pointer_path(root).exists()
