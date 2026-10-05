"""What a host ``server start`` fetches before it spawns the daemon.

Starting the service is the consent to fetch what it needs, so a host with no
Qdrant server downloads one unless the operator switched that off. These tests
drive the step that makes that decision - the options the command parsed, the
configured switch, and the binary that resolves - without the accelerator
probe that precedes it or the spawn that follows it.

Pinned to a host installation: only a host provisions, and the client side of
every command has its own module. The provisioner's network half is the shared
recording substitute, so "was a download attempted" is observable and a
regressed run never reaches the network.
"""

from __future__ import annotations

import io
import json
from typing import TYPE_CHECKING, cast

import pytest
import typer

from ..cli._core import _build_console
from ..cli._progress import StartupStatusReporter
from ..cli._service_start import (
    _auto_provision_enabled,
    _ensure_start_dependencies,
    _ServiceStartOptions,
)
from ..config._types import EnvVar
from ..qdrant_runtime._resolve import resolve_binary
from ._cli_helpers import app, runner
from ._qdrant_provision_seam import substitute_qdrant_download
from .conftest import managed_env

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit, pytest.mark.usefixtures("inference_host")]

_SWITCH = EnvVar.QDRANT_AUTO_PROVISION.value


def _options(
    *,
    local_only: bool = False,
    qdrant: bool | None = None,
    qdrant_auto_provision: bool | None = None,
    json_mode: bool = False,
) -> _ServiceStartOptions:
    return _ServiceStartOptions(
        port=8766,
        updates=None,
        update_delay_ms=None,
        repeat_update_delay_s=None,
        local_only=local_only,
        qdrant=qdrant,
        qdrant_auto_provision=qdrant_auto_provision,
        no_preprocess=False,
        json_mode=json_mode,
    )


def _quiet_reporter(*, json_mode: bool = False) -> StartupStatusReporter:
    return StartupStatusReporter(
        json_mode=json_mode,
        console=_build_console(interactive=False, file=io.StringIO()),
        interactive=False,
    )


def _exit_code_of(options: _ServiceStartOptions) -> int | None:
    """Run the step and return the exit code it stopped with, if it stopped.

    Returned rather than expected through ``pytest.raises`` so a test can
    assert what the step did NOT do before it asserts how the step ended: a
    step that wrongly went on to provision also does not exit, and the test
    should fail on the download it was written to forbid.
    """
    try:
        with _quiet_reporter(json_mode=options.json_mode) as reporter:
            _ensure_start_dependencies(options, reporter)
    except typer.Exit as stopped:
        return stopped.exit_code
    return None


@pytest.fixture
def empty_managed_dir(isolated_status_dir: Path) -> Path:
    """An isolated managed directory in which no Qdrant server resolves."""
    assert resolve_binary() is None, (
        "premise: nothing may already resolve, or the step returns before it "
        "decides anything"
    )
    return isolated_status_dir


class TestTheSwitch:
    """The flag decides for one run; unset, the configured switch stands."""

    def test_provisioning_is_on_unless_something_turns_it_off(self) -> None:
        with managed_env(**{_SWITCH: None}):
            assert _auto_provision_enabled(None) is True

    def test_the_setting_turns_it_off(self) -> None:
        with managed_env(**{_SWITCH: "0"}):
            assert _auto_provision_enabled(None) is False

    def test_either_spelling_of_the_flag_outranks_the_setting(self) -> None:
        with managed_env(**{_SWITCH: "0"}):
            assert _auto_provision_enabled(True) is True
        with managed_env(**{_SWITCH: "1"}):
            assert _auto_provision_enabled(False) is False

    def test_help_offers_both_spellings(self) -> None:
        result = runner.invoke(app, ["server", "start", "--help"])

        assert result.exit_code == 0, result.output
        flattened = " ".join(result.output.split())
        assert "--qdrant-auto-provision" in flattened
        assert "--no-qdrant-auto-provision" in flattened


@pytest.mark.usefixtures("empty_managed_dir")
class TestAHostStartWithNoServer:
    """The decision a start makes when no Qdrant server resolves."""

    def test_a_plain_start_provisions_without_being_asked(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """No flag and no setting: the download happens.

        This is the default command on a machine that has never provisioned
        anything, which used to stop and print an install command.
        """
        calls = substitute_qdrant_download(monkeypatch, succeeds=True)

        with managed_env(**{_SWITCH: None}):
            exit_code = _exit_code_of(_options())

        assert calls == ["provision"]
        assert exit_code is None
        assert "Installed Qdrant server" in capsys.readouterr().out

    def test_the_setting_restores_the_install_instruction(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Switched off, nothing is fetched and the remedy is named.

        Mutation check: with the configured switch ignored and provisioning
        always on, the substitute is reached and the ``calls`` assertion fails
        with ``['provision']``; restoring the read passes.
        """
        calls = substitute_qdrant_download(monkeypatch, succeeds=True)

        with managed_env(**{_SWITCH: "0"}):
            exit_code = _exit_code_of(_options())

        assert calls == [], "a download was attempted with the switch off"
        assert exit_code == 1
        output = capsys.readouterr().out
        assert "Run: vaultspec-rag server qdrant install" in output
        assert "vaultspec-rag server start --local-only" in output

    def test_the_opt_out_flag_outranks_a_setting_that_allows_it(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """``--no-qdrant-auto-provision`` is one envelope and no download.

        Mutation check: with the flag dropped on the way to the binary check,
        the allowing setting wins, the substitute is reached, and the
        ``calls`` assertion fails with ``['provision']``; restoring it passes.
        """
        calls = substitute_qdrant_download(monkeypatch, succeeds=True)

        with managed_env(**{_SWITCH: "1"}):
            exit_code = _exit_code_of(
                _options(qdrant_auto_provision=False, json_mode=True)
            )

        assert calls == [], "a download was attempted against the opt-out flag"
        assert exit_code == 1
        payload = cast("dict[str, object]", json.loads(capsys.readouterr().out))
        assert payload["ok"] is False
        assert payload["command"] == "service.start"
        assert payload["error"] == "qdrant_missing"

    def test_the_opt_in_flag_outranks_a_setting_that_forbids_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = substitute_qdrant_download(monkeypatch, succeeds=True)

        with managed_env(**{_SWITCH: "0"}):
            exit_code = _exit_code_of(_options(qdrant_auto_provision=True))

        assert calls == ["provision"]
        assert exit_code is None

    @pytest.mark.parametrize(
        "selection",
        [{"local_only": True}, {"qdrant": False}],
        ids=["local-only", "no-qdrant"],
    )
    def test_the_on_disk_store_never_touches_the_server(
        self,
        monkeypatch: pytest.MonkeyPatch,
        selection: dict[str, bool],
        empty_managed_dir: Path,
    ) -> None:
        """Neither opt-out fetches the server, and neither fails for lacking it.

        Mutation check: with the on-disk selection ignored, both shapes reach
        the substitute and fail the ``calls`` assertion with ``['provision']``;
        restoring the early return passes.
        """
        calls = substitute_qdrant_download(monkeypatch, succeeds=True)

        with managed_env(**{_SWITCH: "1"}):
            exit_code = _exit_code_of(_options(**selection))

        assert calls == [], "the on-disk store reached the Qdrant provisioner"
        assert exit_code is None
        assert not any(empty_managed_dir.iterdir())

    def test_a_failed_download_is_one_envelope_and_no_progress_text(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Every way the provisioner declines reaches a broker as one document.

        The provisioner reports an unsupported platform, a refused source and a
        digest mismatch alike as a failed report with its reason, so this is
        the one branch all of them leave through.
        """
        calls = substitute_qdrant_download(monkeypatch, succeeds=False)

        with managed_env(**{_SWITCH: None}):
            exit_code = _exit_code_of(_options(json_mode=True))

        assert calls == ["provision"]
        assert exit_code == 1
        captured = capsys.readouterr()
        payload = cast("dict[str, object]", json.loads(captured.out))
        assert payload["error"] == "qdrant_provision_failed"
        data = cast("dict[str, object]", payload["data"])
        assert data["detail"] == "SHA256 mismatch for the release archive"
        assert "Downloading the Qdrant server" not in captured.out
        assert "Downloading the Qdrant server" not in captured.err


class TestAnOperatorNamedBinary:
    """A binary the operator named is used as named, or the start fails."""

    def test_an_unusable_setting_is_one_envelope_and_never_a_download(
        self,
        monkeypatch: pytest.MonkeyPatch,
        isolated_status_dir: Path,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The operator asked for one server and must not silently get another.

        Mutation check: with the refusal swallowed and treated as "nothing
        resolved", the start goes on to provision, the substitute is reached,
        and the ``calls`` assertion fails with ``['provision']``; restoring the
        failure passes.
        """
        del isolated_status_dir
        calls = substitute_qdrant_download(monkeypatch, succeeds=False)
        missing = tmp_path / "no-such-qdrant"

        with managed_env(**{EnvVar.QDRANT_BINARY.value: str(missing), _SWITCH: "1"}):
            exit_code = _exit_code_of(_options(json_mode=True))

        assert calls == [], "an unusable operator binary was replaced by a download"
        assert exit_code == 1
        payload = cast("dict[str, object]", json.loads(capsys.readouterr().out))
        assert payload["ok"] is False
        assert payload["error"] == "qdrant_binary_invalid"
        data = cast("dict[str, object]", payload["data"])
        assert EnvVar.QDRANT_BINARY.value in str(data["detail"])
        assert str(missing) in str(data["detail"])
