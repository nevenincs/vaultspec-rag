"""CLI tests for the managed Qdrant operator surface."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from ..cli import app
from ..config._types import EnvVar
from ..qdrant_runtime._constants import QDRANT_SERVER_VERSION
from ..qdrant_runtime._resolve import binary_filename

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]

runner = CliRunner()


def _labels(output: str) -> dict[str, str]:
    labels: dict[str, str] = {}
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or ":" not in line:
            continue
        label, value = line.split(":", 1)
        labels[label] = value.strip()
    return labels


_FAKE_SERVER = b"test-qdrant"


def _seed_qdrant_install(
    status_dir: Path,
    version: str = QDRANT_SERVER_VERSION,
    *,
    registered: bool = False,
) -> None:
    """Write a managed install whose executable is a few fixture bytes.

    A ``download`` install is held to the committed digest of a release asset,
    which fixture bytes can never match, so it resolves and then fails its
    check - the state of a tampered install. ``registered`` writes the install
    the way ``server qdrant install --binary`` records one: operator-sourced
    and held to the digest recorded for these same bytes, so it may run.
    """
    bin_dir = status_dir / "bin" / "qdrant" / version
    bin_dir.mkdir(parents=True)
    (bin_dir / binary_filename()).write_bytes(_FAKE_SERVER)
    manifest: dict[str, str] = {
        "version": version,
        "source": "download",
        "provisioned_at": "2026-06-12T00:00:00+00:00",
    }
    if registered:
        manifest["source"] = "operator"
        manifest["binary_sha256"] = hashlib.sha256(_FAKE_SERVER).hexdigest()
    (bin_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def _closed_port() -> int:
    import socket

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


def test_server_start_help_exposes_qdrant_options_in_operator_language() -> None:
    result = runner.invoke(app, ["server", "start", "--help"])

    assert result.exit_code == 0, result.output
    assert "--qdrant" in result.output
    assert "--qdrant-auto-provision" in result.output
    assert "managed Qdrant server" in result.output
    for old_term in ("pinned Rust", "binary", "loopback child"):
        assert old_term not in result.output


def test_qdrant_help_uses_managed_server_language() -> None:
    result = runner.invoke(app, ["server", "qdrant", "--help"])

    assert result.exit_code == 0, result.output
    assert "managed Qdrant server" in result.output
    assert "install" in result.output
    assert "status" in result.output
    assert "clean" in result.output
    for old_term in ("supervised qdrant server binary", "pinned", "bin dir"):
        assert old_term not in result.output


def test_qdrant_status_is_operator_facing_when_not_installed(tmp_path: Path) -> None:
    help_result = runner.invoke(app, ["server", "qdrant", "status", "--help"])
    assert help_result.exit_code == 0, help_result.output
    assert "Emit JSON for scripts instead of human text" in help_result.output
    assert "--port" in help_result.output
    assert "Qdrant HTTP port to check" in help_result.output

    port = _closed_port()
    result = runner.invoke(
        app,
        [
            "server",
            "qdrant",
            "status",
        ],
        env={
            EnvVar.STATUS_DIR.value: str(tmp_path),
            EnvVar.QDRANT_PORT.value: str(port),
        },
    )

    assert result.exit_code == 0, result.output
    labels = _labels(result.output)
    assert result.output.splitlines()[0] == "Qdrant storage service"
    assert labels["Managed version"] == QDRANT_SERVER_VERSION
    assert labels["Executable"] == "not installed"
    assert labels["Address"] == f"http://127.0.0.1:{port}"
    assert labels["Connection"] == "not accepting requests"
    assert labels["Process"] == "not started by vaultspec-rag"
    assert labels["Available installs"] == "none"
    assert "vaultspec-rag server qdrant install" in result.output


def test_qdrant_status_is_actionable_when_installed_but_not_running(
    tmp_path: Path,
) -> None:
    """A registered operator binary is labelled as one, and may be started.

    Mutation check: with the operator-supplied wording dropped from the source
    label, the ``Source`` assertion fails; restoring it passes.
    """
    _seed_qdrant_install(tmp_path, registered=True)
    port = _closed_port()

    result = runner.invoke(
        app,
        ["server", "qdrant", "status", "--port", str(port)],
        env={
            EnvVar.STATUS_DIR.value: str(tmp_path),
            EnvVar.QDRANT_PORT.value: str(_closed_port()),
        },
    )

    assert result.exit_code == 0, result.output
    labels = _labels(result.output)
    assert labels["Executable"].endswith(binary_filename())
    assert labels["Source"] == "operator-supplied (registered)"
    assert "Detail" not in labels
    assert labels["Address"] == f"http://127.0.0.1:{port}"
    assert labels["Connection"] == "not accepting requests"
    assert "Next action:" in result.output
    assert "vaultspec-rag server start --qdrant" in result.output
    assert "Available installs:" in result.output
    assert f"{QDRANT_SERVER_VERSION} - operator-supplied (current)" in result.output


def test_qdrant_status_labels_a_binary_named_by_the_operator_setting(
    tmp_path: Path,
) -> None:
    """A binary named by the setting is operator-supplied in both views."""
    supplied = tmp_path / "operator-qdrant"
    supplied.write_bytes(_FAKE_SERVER)
    env = {
        EnvVar.STATUS_DIR.value: str(tmp_path / "managed"),
        EnvVar.QDRANT_PORT.value: str(_closed_port()),
        EnvVar.QDRANT_BINARY.value: str(supplied),
    }

    human = runner.invoke(app, ["server", "qdrant", "status"], env=env)
    machine = runner.invoke(app, ["server", "qdrant", "status", "--json"], env=env)

    assert human.exit_code == 0, human.output
    assert _labels(human.output)["Source"] == "operator-supplied (env)"
    assert machine.exit_code == 0, machine.output
    data = json.loads(machine.stdout)["data"]
    assert data["active_binary"]["source"] == "env"
    assert data["active_binary"]["operator_supplied"] is True
    assert data["binary_error"] is None


def test_qdrant_status_reports_an_install_that_fails_its_check(
    tmp_path: Path,
) -> None:
    """A managed install a start would refuse is not shown as startable.

    Mutation check: with status no longer holding the resolved binary to its
    check, the view offers ``server start --qdrant`` for an install that
    cannot run - failing the next-action assertion, and the ``Detail``
    assertion before it. Restoring the check passes.
    """
    _seed_qdrant_install(tmp_path)
    env = {
        EnvVar.STATUS_DIR.value: str(tmp_path),
        EnvVar.QDRANT_PORT.value: str(_closed_port()),
    }

    human = runner.invoke(app, ["server", "qdrant", "status"], env=env)
    machine = runner.invoke(app, ["server", "qdrant", "status", "--json"], env=env)

    assert human.exit_code == 0, human.output
    labels = _labels(human.output)
    assert labels["Executable"].endswith(binary_filename())
    assert labels["Source"] == "managed download (provisioned)"
    assert "server qdrant install --upgrade" in labels.get("Detail", "")
    assert "vaultspec-rag server start --qdrant" not in human.output
    assert f"{QDRANT_SERVER_VERSION} - downloaded release (current)" in human.output
    assert machine.exit_code == 0, machine.output
    data = json.loads(machine.stdout)["data"]
    assert data["binary_error"]["error"] == "qdrant_binary_unverified"


def test_qdrant_status_reports_an_unusable_operator_setting(tmp_path: Path) -> None:
    """A setting that names nothing usable is reported, not a traceback.

    The view is where an operator looks when a start has just failed on that
    setting, so it has to render.
    """
    missing = tmp_path / "no-such-qdrant"
    env = {
        EnvVar.STATUS_DIR.value: str(tmp_path / "managed"),
        EnvVar.QDRANT_PORT.value: str(_closed_port()),
        EnvVar.QDRANT_BINARY.value: str(missing),
    }

    human = runner.invoke(app, ["server", "qdrant", "status"], env=env)
    machine = runner.invoke(app, ["server", "qdrant", "status", "--json"], env=env)

    assert human.exit_code == 0, human.output
    labels = _labels(human.output)
    assert labels["Executable"] == "not usable"
    assert EnvVar.QDRANT_BINARY.value in labels["Detail"]
    assert "vaultspec-rag server qdrant install" not in human.output
    assert machine.exit_code == 0, machine.output
    data = json.loads(machine.stdout)["data"]
    assert data["active_binary"] is None
    assert data["binary_error"]["error"] == "qdrant_binary_invalid"


@pytest.mark.usefixtures("inference_host")
def test_qdrant_install_dry_run_uses_install_language(tmp_path: Path) -> None:
    help_result = runner.invoke(app, ["server", "qdrant", "install", "--help"])
    assert help_result.exit_code == 0, help_result.output
    assert "Emit JSON for scripts instead of human text" in help_result.output
    assert "JSON envelope" not in help_result.output

    result = runner.invoke(
        app,
        [
            "server",
            "qdrant",
            "install",
            "--dry-run",
        ],
        env={EnvVar.STATUS_DIR.value: str(tmp_path)},
    )

    assert result.exit_code == 0, result.output
    labels = _labels(result.output)
    assert labels["Action"] == "dry run"
    assert labels["Version"]
    assert labels["Release package"]
    assert labels["Download"].startswith("https://github.com/qdrant/qdrant/")
    assert labels["Install"]
    assert "Binary:" not in result.output
    assert "Asset:" not in result.output
    assert "URL:" not in result.output


def test_qdrant_clean_help_names_destructive_target() -> None:
    result = runner.invoke(app, ["server", "qdrant", "clean", "--help"])

    assert result.exit_code == 0, result.output
    assert "managed Qdrant server installs" in result.output
    assert "Confirm deletion of managed Qdrant installs" in result.output
    assert "Emit JSON for scripts instead of human text" in result.output
    assert "JSON envelope" not in result.output
    for old_term in ("provisioned qdrant binaries", "managed bin dir", "pinned"):
        assert old_term not in result.output


def test_qdrant_clean_dry_run_empty_uses_install_language(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["server", "qdrant", "clean", "--dry-run"],
        env={EnvVar.STATUS_DIR.value: str(tmp_path)},
    )

    assert result.exit_code == 0, result.output
    assert "No managed Qdrant installs would be removed." in result.output
    assert "Dry run - no managed Qdrant installs were removed." in result.output
    assert "Nothing to remove" not in result.output


def test_qdrant_clean_dry_run_lists_installed_versions(tmp_path: Path) -> None:
    _seed_qdrant_install(tmp_path)

    result = runner.invoke(
        app,
        ["server", "qdrant", "clean", "--dry-run"],
        env={EnvVar.STATUS_DIR.value: str(tmp_path)},
    )

    assert result.exit_code == 0, result.output
    assert (
        f"Would remove installed Qdrant versions: {QDRANT_SERVER_VERSION}"
        in result.output
    )
    assert "Dry run - no managed Qdrant installs were removed." in result.output
    assert "Would remove:" not in result.output
    assert "Nothing to remove" not in result.output
