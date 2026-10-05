"""CLI tests for the managed Qdrant operator surface."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from ..cli import app
from ..config._types import EnvVar
from ..qdrant_runtime._constants import QDRANT_SERVER_VERSION
from ._loopback_tls import send_bytes, trusted_loopback_sources
from ._qdrant_provision_seam import operator_pair, write_unpinned_install

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
    status_dir: Path, version: str = QDRANT_SERVER_VERSION
) -> None:
    """Write a managed install under *status_dir*, before any command reads it.

    Its executable is fixture bytes, so it is an install that is not the
    pinned release, whatever its manifest claims.
    """
    write_unpinned_install(status_dir / "bin" / "qdrant" / version, _FAKE_SERVER)


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


def test_qdrant_status_labels_an_operator_binary_and_offers_the_start(
    tmp_path: Path,
) -> None:
    """A binary named with its digest is operator-supplied in both views.

    It is the one stand-in that can verify: a managed install is held to the
    digest committed for its release, which fixture bytes never match.

    Mutation check: with the operator-supplied wording dropped from the source
    label, the ``Source`` assertion fails; restoring it passes.
    """
    supplied = tmp_path / "operator-qdrant"
    supplied.write_bytes(_FAKE_SERVER)
    env = {
        EnvVar.STATUS_DIR.value: str(tmp_path / "managed"),
        EnvVar.QDRANT_PORT.value: str(_closed_port()),
        **operator_pair(supplied),
    }

    human = runner.invoke(app, ["server", "qdrant", "status"], env=env)
    machine = runner.invoke(app, ["server", "qdrant", "status", "--json"], env=env)

    assert human.exit_code == 0, human.output
    labels = _labels(human.output)
    assert labels["Executable"] == str(supplied)
    assert labels["Source"] == "operator-supplied (env)"
    assert "Detail" not in labels
    assert labels["Connection"] == "not accepting requests"
    assert "vaultspec-rag server start --qdrant" in human.output
    assert labels["Available installs"] == "none"
    assert machine.exit_code == 0, machine.output
    data = json.loads(machine.stdout)["data"]
    assert data["active_binary"]["source"] == "env"
    assert data["active_binary"]["operator_supplied"] is True
    assert data["binary_error"] is None


def test_qdrant_status_reports_an_operator_file_that_is_not_the_one_declared(
    tmp_path: Path,
) -> None:
    """A file that no longer hashes to its declared digest is not startable.

    Mutation check: with status no longer holding the resolved binary to its
    check, the view carries no refusal, failing the ``Detail`` assertion;
    restoring the check passes.
    """
    supplied = tmp_path / "operator-qdrant"
    supplied.write_bytes(_FAKE_SERVER)
    env = {
        EnvVar.STATUS_DIR.value: str(tmp_path / "managed"),
        EnvVar.QDRANT_PORT.value: str(_closed_port()),
        **operator_pair(supplied),
    }
    supplied.write_bytes(b"replaced after it was declared")

    human = runner.invoke(app, ["server", "qdrant", "status"], env=env)
    machine = runner.invoke(app, ["server", "qdrant", "status", "--json"], env=env)

    assert human.exit_code == 0, human.output
    labels = _labels(human.output)
    assert labels["Source"] == "operator-supplied (env)"
    assert EnvVar.QDRANT_BINARY_SHA256.value in labels.get("Detail", "")
    assert "vaultspec-rag server start --qdrant" not in human.output
    data = json.loads(machine.stdout)["data"]
    assert data["binary_error"]["error"] == "qdrant_binary_unverified"


def test_qdrant_status_reports_an_install_that_is_not_the_pinned_release(
    tmp_path: Path,
) -> None:
    """A managed install a start would refuse is not shown as startable.

    Its executable hashes to no committed digest, so it is reported as
    unusable whatever its manifest claims, with every way out named in full:
    the pinned release installed over it, online or from a local archive, or
    the two settings for an operator's own binary. The listing says the same
    thing in its own words and does not give the install the source its
    manifest claims.

    Mutation check: with the resolver's refusal taken as "nothing installed",
    the view reads ``not installed`` and offers a plain install, which would
    refuse - failing the ``Executable`` assertion. Restoring it passes.
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
    assert labels["Executable"] == "not usable"
    detail = labels["Detail"]
    assert "server qdrant install --upgrade" in detail
    assert "server qdrant install --upgrade --archive <file>" in detail
    assert EnvVar.QDRANT_BINARY.value in detail
    assert EnvVar.QDRANT_BINARY_SHA256.value in detail
    assert "vaultspec-rag server start --qdrant" not in human.output
    assert f"{QDRANT_SERVER_VERSION} - not verified (current)" in human.output
    assert "downloaded release" not in human.output
    # The listing would give the same sentence as its reason; it is said once.
    assert " ".join(human.output.split()).count("is not the pinned release") == 1
    assert machine.exit_code == 0, machine.output
    data = json.loads(machine.stdout)["data"]
    assert data["active_binary"] is None
    assert data["binary_error"]["error"] == "qdrant_binary_unverified"
    assert data["provisioned"][0]["verified"] is False


def test_qdrant_status_reports_an_unusable_operator_setting(tmp_path: Path) -> None:
    """A pair that names nothing usable is reported, not a traceback.

    The view is where an operator looks when a start has just failed on that
    setting, so it has to render.
    """
    missing = tmp_path / "no-such-qdrant"
    env = {
        EnvVar.STATUS_DIR.value: str(tmp_path / "managed"),
        EnvVar.QDRANT_PORT.value: str(_closed_port()),
        EnvVar.QDRANT_BINARY.value: str(missing),
        EnvVar.QDRANT_BINARY_SHA256.value: "0" * 64,
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


def _assert_refused_for_half_a_pair(argv: list[str], env: dict[str, str]) -> None:
    human = runner.invoke(app, argv, env=env)
    machine = runner.invoke(app, [*argv, "--json"], env=env)

    assert human.exit_code == 1, human.output
    assert "must be set together" in human.output
    assert EnvVar.QDRANT_BINARY.value in human.output
    assert EnvVar.QDRANT_BINARY_SHA256.value in human.output
    assert "use the managed install" in human.output
    assert machine.exit_code == 1, machine.output
    document = json.loads(machine.stdout)
    assert document["status"] == "failed"
    assert "must be set together" in document["data"]["message"]


@pytest.mark.parametrize(
    "argv",
    [
        ["server", "qdrant", "status"],
        ["server", "qdrant", "install", "--dry-run"],
        ["server", "status"],
    ],
    ids=["qdrant-status", "qdrant-install", "server-status"],
)
def test_an_operator_path_without_its_digest_is_one_failed_outcome(
    tmp_path: Path, argv: list[str]
) -> None:
    """A binary named without a digest stops the command, naming both routes.

    The half pair is refused where settings are read, so no view renders it
    as an operator binary and no verb acts on it. The one message names both
    settings and the way back to the managed install: one line for a person,
    one document for a script.
    """
    supplied = tmp_path / "operator-qdrant"
    supplied.write_bytes(_FAKE_SERVER)

    _assert_refused_for_half_a_pair(
        argv,
        {
            EnvVar.STATUS_DIR.value: str(tmp_path / "managed"),
            EnvVar.QDRANT_STORAGE_DIR.value: str(tmp_path / "qdrant" / "storage"),
            EnvVar.QDRANT_BINARY.value: str(supplied),
        },
    )


def test_a_start_with_an_operator_path_and_no_digest_starts_nothing(
    tmp_path: Path,
) -> None:
    """``server start`` meets the same refusal before it looks at anything.

    Aimed at a port something else holds, so a start that got past the
    settings would stop there instead of creating a process: the refusal
    asserted is the settings one, and a regression cannot spawn a service.

    Mutation check: with a path that lacks its digest read as "no operator
    binary", the start reaches the port check and stops there, failing the
    ``must be set together`` assertion; the three read-only verbs render
    their views and fail on the exit code. Restoring the refusal passes all
    four.
    """
    import socket

    supplied = tmp_path / "operator-qdrant"
    supplied.write_bytes(_FAKE_SERVER)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as held:
        held.bind(("127.0.0.1", 0))
        held.listen(1)

        _assert_refused_for_half_a_pair(
            ["server", "start", "--port", str(held.getsockname()[1])],
            {
                EnvVar.STATUS_DIR.value: str(tmp_path / "managed"),
                EnvVar.QDRANT_STORAGE_DIR.value: str(tmp_path / "qdrant" / "storage"),
                EnvVar.QDRANT_BINARY.value: str(supplied),
            },
        )


@pytest.mark.usefixtures("inference_host")
def test_qdrant_install_dry_run_uses_install_language(tmp_path: Path) -> None:
    help_result = runner.invoke(app, ["server", "qdrant", "install", "--help"])
    assert help_result.exit_code == 0, help_result.output
    assert "Emit JSON for scripts instead of human text" in help_result.output
    assert "JSON envelope" not in help_result.output
    assert "--archive" in help_result.output
    assert "--binary" not in help_result.output

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
    assert labels["Source"].startswith(
        "download from https://github.com/qdrant/qdrant/"
    )
    assert labels["Install"]
    assert "Binary:" not in result.output
    assert "Asset:" not in result.output
    assert "URL:" not in result.output


@pytest.mark.usefixtures("inference_host")
def test_qdrant_install_from_a_local_archive_says_so_and_asks_nobody(
    tmp_path: Path,
) -> None:
    """The report names the archive as the source, in both views.

    A preview, so nothing is read or written: what is held here is that the
    verb takes the file, hands it on, and reports it as what the install
    would come from - with no release address beside it to suggest a request.

    Mutation check: with the report always naming a download as its source,
    the ``Source`` assertion fails; restoring it passes.
    """
    local = tmp_path / "from-a-usb-stick.bin"
    local.write_bytes(b"a local copy of the release package")
    argv = ["server", "qdrant", "install", "--dry-run", "--archive", str(local)]
    env = {EnvVar.STATUS_DIR.value: str(tmp_path / "managed")}

    human = runner.invoke(app, argv, env=env)
    machine = runner.invoke(app, [*argv, "--json"], env=env)

    assert human.exit_code == 0, human.output
    flattened = " ".join(human.output.split())
    assert f"Source: local archive {local} (no request was made)" in flattened
    assert "download from" not in human.output
    assert machine.exit_code == 0, machine.output
    data = json.loads(machine.stdout)["data"]
    assert data["action"] == "dry_run"
    assert data["source"] == "archive"
    assert data["url"] == ""


@pytest.mark.usefixtures("inference_host")
def test_qdrant_install_reads_the_file_it_was_given_and_asks_nobody(
    tmp_path: Path,
) -> None:
    """The verb installs from the file, and a wrong file fails as one document.

    The release address is a loopback source that would answer, so a run that
    reached for the network instead of the file shows up in its log. No
    stand-in can match the committed digest, so the run that is driven is the
    refusal, which names the file. That a refused file is left untouched and
    nothing is installed from it is held where the provisioner is tested;
    what is held here is that the verb hands the file on and reports once.

    Mutation check: with the verb no longer handing the file to the
    provisioner, the run asks the release source for the archive, failing the
    ``requests`` assertion; restoring it passes.
    """
    local = tmp_path / "not-the-release.zip"
    local.write_bytes(b"something else entirely")
    argv = ["server", "qdrant", "install", "--archive", str(local), "--json"]

    with trusted_loopback_sources(tmp_path / "tls") as sources:
        release = sources.serve(lambda handler: send_bytes(handler, b"a release"))
        result = runner.invoke(
            app,
            argv,
            env={
                EnvVar.STATUS_DIR.value: str(tmp_path / "managed"),
                EnvVar.QDRANT_STORAGE_DIR.value: str(tmp_path / "qdrant" / "storage"),
                EnvVar.QDRANT_RELEASE_BASE_URL.value: release.url("/mirror"),
            },
        )
        asked = release.requests

    assert asked == [], "the release source was asked for a file given locally"
    assert result.exit_code == 1, result.output
    document = json.loads(result.stdout)
    assert document["ok"] is False
    assert document["data"]["action"] == "failed"
    assert document["data"]["source"] is None
    assert str(local) in document["message"]


def test_the_registration_option_is_gone_not_deprecated() -> None:
    """``--binary`` is refused as an unknown option, with nothing provisioned."""
    result = runner.invoke(app, ["server", "qdrant", "install", "--binary", "anything"])

    assert result.exit_code == 2, result.output
    assert "No such option" in result.output


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
