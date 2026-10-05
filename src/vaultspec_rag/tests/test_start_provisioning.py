"""What a host ``server start`` fetches before it spawns the daemon.

Starting the service is the consent to fetch what it needs, so a host with no
model files or no Qdrant server gets them in the foreground, unless the
operator switched the server download off. These tests drive the step that
does that - the options the command parsed, the configured switch, the model
cache, and the binary that resolves - without the accelerator probe that
precedes it or the spawn that follows it.

Pinned to a host installation: only a host provisions, and the client side of
every command has its own module. Two things are staged so the outcome does
not depend on the machine. The model cache is a directory the test seeds, read
by the product's own completeness probe, with the hub's offline switch set so
nothing can be downloaded into it. Where a start is meant to fetch the server,
the real provisioner fetches a stand-in release from a loopback source that
logs every request; where it must not, the provisioner is replaced by a
recorder, so a regressed run is seen and never reaches a release source.
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
    _decide_backend,
    _ensure_start_dependencies,
    _ServiceStartOptions,
)
from ..config._types import EnvVar
from ..qdrant_runtime._constants import MANIFEST_SOURCE_UNRECORDED, BinarySource
from ..qdrant_runtime._resolve import (
    qdrant_bin_dir,
    read_manifest,
    resolve_binary,
)
from ._cli_helpers import app, runner
from ._loopback_tls import trusted_loopback_sources
from ._model_cache_seed import seed_model_cache
from ._qdrant_provision_seam import (
    RECORDED_FAILURE,
    operator_pair,
    record_qdrant_provisioning,
    write_unpinned_install,
)
from ._stand_in_release import (
    abandon_a_working_file,
    place_stand_in,
    served_stand_in,
    working_files,
)
from .conftest import managed_env

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from ._loopback_tls import LoopbackSources
    from ._stand_in_release import ServedRelease

pytestmark = [pytest.mark.unit, pytest.mark.usefixtures("inference_host")]

_SWITCH = EnvVar.QDRANT_AUTO_PROVISION.value
_ABSENT_MODEL = "vaultspec-test/absent-reranker"


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


def _reporter_into(
    buffer: io.StringIO, *, json_mode: bool = False
) -> StartupStatusReporter:
    return StartupStatusReporter(
        json_mode=json_mode,
        console=_build_console(interactive=False, file=buffer),
        interactive=False,
        static_interval_s=0.0,
    )


def _exit_code_of(
    options: _ServiceStartOptions, *, progress: io.StringIO | None = None
) -> int | None:
    """Run the step and return the exit code it stopped with, if it stopped.

    Returned rather than expected through ``pytest.raises`` so a test can
    assert what the step did NOT do before it asserts how the step ended: a
    step that wrongly went on to provision also does not exit, and the test
    should fail on the download it was written to forbid.
    """
    buffer = io.StringIO() if progress is None else progress
    backend = _decide_backend(local_only=options.local_only, qdrant=options.qdrant)
    try:
        with _reporter_into(buffer, json_mode=options.json_mode) as reporter:
            _ensure_start_dependencies(options, backend, reporter)
    except typer.Exit as stopped:
        return stopped.exit_code
    return None


@pytest.fixture
def offline_hub() -> Generator[None]:
    """Set the hub's offline switch, so no test here can start a download."""
    with managed_env(**{EnvVar.HF_HUB_OFFLINE.value: "1"}):
        yield


@pytest.fixture
def host_with_models(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    isolated_status_dir: Path,
    offline_hub: None,
) -> Path:
    """A host whose models are all cached and whose managed directory is empty.

    The state every Qdrant decision below starts from: the model step has
    nothing to do, and no Qdrant server resolves.
    """
    del offline_hub
    seed_model_cache(monkeypatch, tmp_path / "hf-cache")
    assert resolve_binary() is None, (
        "premise: nothing may already resolve, or the step returns before it "
        "decides anything"
    )
    return isolated_status_dir


@pytest.fixture
def sources(tmp_path: Path) -> Generator[LoopbackSources]:
    with trusted_loopback_sources(tmp_path / "tls") as started:
        yield started


@pytest.fixture
def release(
    sources: LoopbackSources, host_with_models: Path
) -> Generator[ServedRelease]:
    """A stand-in release, pinned and served as the configured release source."""
    del host_with_models
    with served_stand_in(sources) as served:
        yield served


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


@pytest.mark.usefixtures("host_with_models")
class TestAHostStartWithNoServer:
    """The decision a start makes when no Qdrant server resolves."""

    def test_a_plain_start_provisions_without_being_asked(
        self,
        release: ServedRelease,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """No flag and no setting: the download happens, and is reported.

        This is the default command on a machine that has never provisioned
        anything, which used to stop and print an install command. The real
        provisioner fetches the pinned release from the configured source,
        and what it installed is what then resolves. The outcome is rendered
        in the words ``install`` uses for the same two steps.

        Mutation check: with provisioning switched off whatever the setting
        says, the source is never asked and the request assertion fails;
        restoring the read passes.
        """
        with managed_env(**{_SWITCH: None}):
            exit_code = _exit_code_of(_options())

        assert len(release.source.requests) == 1, "the release was not fetched once"
        assert exit_code is None
        resolved = resolve_binary()
        assert resolved is not None
        assert resolved.source is BinarySource.MANAGED_DOWNLOAD
        assert working_files(qdrant_bin_dir()) == []
        output = capsys.readouterr().out
        assert "Models: already present" in output
        assert "Qdrant binary: downloaded" in output

    def test_download_progress_reaches_the_operator(
        self, release: ServedRelease
    ) -> None:
        """A first-use download reports its stages through the start reporter.

        The only place a provision runs unattended, and so the only place a
        silent one reads as a hung start rather than as a command the operator
        chose to run.
        """
        progress = io.StringIO()

        with managed_env(**{_SWITCH: None}):
            exit_code = _exit_code_of(_options(), progress=progress)

        assert len(release.source.requests) == 1
        assert exit_code is None
        reported = progress.getvalue()
        assert "Downloading the Qdrant server" in reported
        assert "Verifying the Qdrant download checksum" in reported

    def test_a_second_start_downloads_nothing(self, release: ServedRelease) -> None:
        """An install that is already the pinned release is left as it is."""
        with managed_env(**{_SWITCH: None}):
            assert _exit_code_of(_options()) is None
            asked = len(release.source.requests)

            exit_code = _exit_code_of(_options())

        assert exit_code is None
        assert len(release.source.requests) == asked

    def test_a_start_finishes_what_a_killed_install_left(
        self,
        release: ServedRelease,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The pinned executable with no manifest starts, and is put in order.

        A run killed between moving the executable into place and recording
        it leaves exactly this, with its download beside it. Every later
        start used to refuse it and name a flag the start does not have. The
        executable already is the pinned release, so nothing is fetched: the
        manifest is written again and the abandoned working file is removed.

        Mutation check: with the start leaving a resolved managed install
        alone instead of handing it to the provisioner, the manifest
        assertion fails; restoring the call passes.
        """
        version_dir = qdrant_bin_dir()
        place_stand_in()
        abandon_a_working_file(version_dir)

        with managed_env(**{_SWITCH: None}):
            exit_code = _exit_code_of(_options())

        assert exit_code is None
        assert release.source.requests == [], "a pinned install was fetched again"
        manifest = read_manifest(version_dir)
        assert manifest is not None, "the manifest was not written again"
        assert manifest["source"] == MANIFEST_SOURCE_UNRECORDED
        assert working_files(version_dir) == []
        assert "Qdrant binary:" in capsys.readouterr().out

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
        calls = record_qdrant_provisioning(monkeypatch)

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

        Mutation check: with the flag dropped on the way to the front door,
        the allowing setting wins, the substitute is reached, and the
        ``calls`` assertion fails with ``['provision']``; restoring it passes.
        """
        calls = record_qdrant_provisioning(monkeypatch)

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
        self, release: ServedRelease
    ) -> None:
        with managed_env(**{_SWITCH: "0"}):
            exit_code = _exit_code_of(_options(qdrant_auto_provision=True))

        assert len(release.source.requests) == 1
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
        host_with_models: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Neither opt-out fetches the server, and neither fails for lacking it.

        Mutation check: with the on-disk selection not passed to the front
        door, both shapes reach the substitute and fail the ``calls``
        assertion with ``['provision']``; restoring it passes.
        """
        calls = record_qdrant_provisioning(monkeypatch)

        with managed_env(**{_SWITCH: "1"}):
            exit_code = _exit_code_of(_options(**selection))

        assert calls == [], "the on-disk store reached the Qdrant provisioner"
        assert exit_code is None
        assert not any(host_with_models.iterdir())
        assert "Qdrant binary: skipped" in capsys.readouterr().out

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
        calls = record_qdrant_provisioning(monkeypatch)

        with managed_env(**{_SWITCH: None}):
            exit_code = _exit_code_of(_options(json_mode=True))

        assert calls == ["provision"]
        assert exit_code == 1
        captured = capsys.readouterr()
        payload = cast("dict[str, object]", json.loads(captured.out))
        assert payload["error"] == "qdrant_provision_failed"
        data = cast("dict[str, object]", payload["data"])
        assert data["detail"] == RECORDED_FAILURE
        assert data["step"] == "qdrant"
        assert "Downloading the Qdrant server" not in captured.out
        assert "Downloading the Qdrant server" not in captured.err


@pytest.mark.usefixtures("host_with_models")
class TestAnOperatorNamedBinary:
    """A binary the operator named is used as named, or the start fails."""

    def test_an_operator_binary_is_announced_and_nothing_is_downloaded(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The console says the server is operator-supplied, not only the log.

        No committed pin vouches for such a binary, so a start that uses one
        has to say so where the operator is looking.

        Mutation check: with the operator-supplied wording dropped from the
        resolved binary's detail, the announcement assertion fails; restoring
        it passes.
        """
        calls = record_qdrant_provisioning(monkeypatch)
        supplied = tmp_path / "operator-qdrant"
        supplied.write_bytes(b"operator supplied")

        with managed_env(**operator_pair(supplied)):
            exit_code = _exit_code_of(_options())

        assert calls == [], "an operator binary was replaced by a download"
        assert exit_code is None
        announced = " ".join(capsys.readouterr().out.split())
        assert "operator-supplied binary" in announced
        assert "source: env" in announced
        assert EnvVar.QDRANT_BINARY.value in announced
        assert (
            f"verified against the digest declared in "
            f"{EnvVar.QDRANT_BINARY_SHA256.value}" in announced
        )

    def test_an_operator_binary_that_is_not_the_one_declared_stops_the_start(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A file that no longer hashes to its declared digest starts nothing.

        The announcement says the binary was verified against that digest, so
        it must not be printed for a file that was not. The failure is one
        document, and the managed release is not fetched in its place.

        Mutation check: with the foreground verification removed, the start
        announces the file as verified and exits cleanly, failing the
        exit-code assertion; restoring it passes.
        """
        calls = record_qdrant_provisioning(monkeypatch)
        supplied = tmp_path / "operator-qdrant"
        supplied.write_bytes(b"operator supplied")
        declared = operator_pair(supplied)
        supplied.write_bytes(b"replaced after it was declared")

        with managed_env(**declared, **{_SWITCH: "1"}):
            exit_code = _exit_code_of(_options(json_mode=True))

        assert calls == [], "an unverified operator binary was replaced by a download"
        assert exit_code == 1
        payload = cast("dict[str, object]", json.loads(capsys.readouterr().out))
        assert payload["ok"] is False
        assert payload["error"] == "qdrant_binary_unverified"
        data = cast("dict[str, object]", payload["data"])
        assert EnvVar.QDRANT_BINARY_SHA256.value in str(data["detail"])

    def test_an_unusable_setting_is_one_envelope_and_never_a_download(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The operator asked for one server and must not silently get another.

        Mutation check: with the resolver's refusal swallowed and treated as
        "nothing resolved", the start goes on to provision, the substitute is
        reached, and the ``calls`` assertion fails with ``['provision']``;
        restoring the failure passes.
        """
        calls = record_qdrant_provisioning(monkeypatch)
        missing = tmp_path / "no-such-qdrant"
        named = {
            EnvVar.QDRANT_BINARY.value: str(missing),
            EnvVar.QDRANT_BINARY_SHA256.value: "0" * 64,
        }

        with managed_env(**named, **{_SWITCH: "1"}):
            exit_code = _exit_code_of(_options(json_mode=True))

        assert calls == [], "an unusable operator binary was replaced by a download"
        assert exit_code == 1
        payload = cast("dict[str, object]", json.loads(capsys.readouterr().out))
        assert payload["ok"] is False
        assert payload["error"] == "qdrant_binary_invalid"
        data = cast("dict[str, object]", payload["data"])
        assert EnvVar.QDRANT_BINARY.value in str(data["detail"])
        assert str(missing) in str(data["detail"])

    def test_a_managed_install_that_is_not_the_pinned_release_stops_the_start(
        self,
        monkeypatch: pytest.MonkeyPatch,
        host_with_models: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A tampered install fails on the console, before any daemon exists.

        The daemon would refuse the same binary at spawn, but only in its log.
        The executable matches no committed digest, and what its manifest
        claims changes nothing. The start fails as one document that names
        every way out in full - replace it with the pinned release, online or
        from a local archive, or name a binary of the operator's own - and it
        does not replace the install unasked.

        Mutation check: with the resolver's refusal swallowed and treated as
        "nothing resolved", the start goes on to provision over the install,
        the recorder is reached, and the ``calls`` assertion fails with
        ``['provision']``; restoring the failure passes.
        """
        calls = record_qdrant_provisioning(monkeypatch)
        version_dir = qdrant_bin_dir()
        assert host_with_models in version_dir.parents, "premise: the temp managed dir"
        installed = write_unpinned_install(version_dir, b"not the pinned server")

        with managed_env(**{_SWITCH: "1"}):
            exit_code = _exit_code_of(_options(json_mode=True))

        assert calls == [], "an install that failed its check was replaced unasked"
        assert exit_code == 1
        assert installed.read_bytes() == b"not the pinned server"
        payload = cast("dict[str, object]", json.loads(capsys.readouterr().out))
        assert payload["ok"] is False
        assert payload["error"] == "qdrant_binary_unverified"
        detail = str(cast("dict[str, object]", payload["data"])["detail"])
        assert "`vaultspec-rag server qdrant install --upgrade`" in detail
        assert "server qdrant install --upgrade --archive <file>" in detail
        assert EnvVar.QDRANT_BINARY.value in detail
        assert EnvVar.QDRANT_BINARY_SHA256.value in detail


class TestModelsComeFirst:
    """The model files are ensured before the server, and offline is loud."""

    def test_a_missing_model_with_the_hub_offline_stops_the_start(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        isolated_status_dir: Path,
        offline_hub: None,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Offline with a model missing stops the start, with the remedy.

        A daemon spawned in this state would sit in its warm-up until the
        start timed out. The missing repository is one that exists nowhere,
        so nothing a regression did could fetch it. That the fetch attempts no
        download offline is the model-fetch module's own guard; what is held
        here is that the failure stops the sequence before the server.

        Mutation check: with a failed model step no longer ending the
        sequence, or with the model step moved after the Qdrant step, the
        substitute is reached and the ``calls`` assertion fails with
        ``['provision']``. Restoring each passes.
        """
        del isolated_status_dir, offline_hub
        calls = record_qdrant_provisioning(monkeypatch)

        with managed_env(**{EnvVar.RERANKER_MODEL.value: _ABSENT_MODEL, _SWITCH: "1"}):
            seed_model_cache(
                monkeypatch, tmp_path / "hf-cache", missing=[_ABSENT_MODEL]
            )
            exit_code = _exit_code_of(_options(json_mode=True))

        assert calls == [], "the server was fetched for a host with no models"
        assert exit_code == 1
        payload = cast("dict[str, object]", json.loads(capsys.readouterr().out))
        assert payload["error"] == "models_offline"
        data = cast("dict[str, object]", payload["data"])
        assert data["step"] == "models"
        detail = str(data["detail"])
        assert _ABSENT_MODEL in detail
        assert EnvVar.HF_HUB_OFFLINE.value in detail
        assert "vaultspec-rag server warmup" in detail
