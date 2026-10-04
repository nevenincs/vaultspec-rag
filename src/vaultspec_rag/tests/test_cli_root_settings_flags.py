"""Guards that the root path options actually reach the process settings.

``--data-dir``, ``--storage-dir``, ``--status-dir`` and ``--log-file`` are
the invocation rung of the resolution order, and the root callback is the
only place that rung is applied: every later reader asks for the
process-wide configuration with no arguments at all. When nothing seeds that
configuration from the flags, each flag parses, validates, and then
configures nothing - a run with ``--status-dir`` still writes its service
state to the default directory, with no error to read and no output that
differs. So the assertion has to be on the settings object the rest of the
process reads, not on the command's own output.

Both directions were checked. With the seeding call removed from the root
callback, every test below fails on its own assertion, reporting the default
directory (``~/.vaultspec-rag``) or the workspace-relative data path rather
than the one the flag named. With it restored, all pass.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from ..cli import app
from ..config._settings import get_config
from ._config_fixtures import reset_config
from ._scaffold import make_workspace

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]

runner = CliRunner()


@pytest.fixture(autouse=True)
def _clean_config_singleton() -> object:
    """Leave no seeded configuration behind for the next test to read."""
    reset_config()
    yield None
    reset_config()


def test_root_path_flags_reach_the_configuration_every_reader_sees(
    tmp_path: Path,
) -> None:
    """The flags a subcommand runs under must be the settings it runs on."""
    project = tmp_path / "project"
    project.mkdir()
    root = make_workspace(project)
    data_dir = tmp_path / "chosen-data"
    status_dir = tmp_path / "chosen-status"
    storage_dir = tmp_path / "chosen-store"

    result = runner.invoke(
        app,
        [
            "--target",
            str(root),
            "--data-dir",
            str(data_dir),
            "--status-dir",
            str(status_dir),
            "--storage-dir",
            str(storage_dir),
            "--log-file",
            "chosen.log",
            "preprocess",
            "status",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    config = get_config()
    assert config.data_dir == str(data_dir)
    assert config.status_dir == str(status_dir)
    assert config.qdrant_dir == str(storage_dir)
    assert config.log_file == "chosen.log"


def test_root_flags_reach_the_configuration_for_a_workspaceless_subcommand(
    tmp_path: Path,
) -> None:
    """The server group returns from the callback early and must seed too.

    It is the group that reads ``status_dir`` hardest - service discovery,
    the marker file and the log all live there - and the one whose callback
    path returns before any workspace is resolved, so it needs its own
    assertion rather than inheriting the one above.
    """
    status_dir = tmp_path / "server-status"

    result = runner.invoke(
        app,
        ["--status-dir", str(status_dir), "server", "status", "--json"],
    )

    # An empty status directory holds no service.json, which is exactly what
    # the command reports when it is looking in the directory the flag named.
    assert "No service.json" in result.output
    assert get_config().status_dir == str(status_dir)
