"""Service<->python-env hardening: the start-failure log tail, the status env
label, and the environment classifier.

All real-behavior, no mocks: the log tail against a real temp file, and the env
label against plain dicts.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from ..cli._service_start import (
    _caller_ephemeral_warning,
    _ephemeral_env_warning,
    _tail_daemon_log,
)
from ..cli._status_labels import _status_env_label
from ..operator_state._provisioning import (
    CU130_INDEX_STRATEGY,
    CudaRepairKind,
    ToolReceiptVerdict,
    classify_tool_receipt,
    cuda_remediation,
    environment_python_request,
    inplace_cuda_command,
    published_wheel_platform_tag,
    release_upgrade_command,
    tool_repair_commands,
    tool_upgrade_commands,
    upgrade_commands_for_mode,
)
from ..operator_state._topology import (
    TOOL_RECEIPT_NAME,
    RuntimeEnvKind,
    classify_environment,
    environment_root,
)
from ..torch_config._index import CU130_INDEX_URL

pytestmark = [pytest.mark.unit]


def test_tail_daemon_log_returns_last_nonempty_lines(tmp_path: Path) -> None:
    log = tmp_path / "service.log"
    log.write_text(
        "dropped\nline one\n\n  \nline two\nthree\nfour\nfive\n"
        "RuntimeError: CUDA GPU required\n",
        encoding="utf-8",
    )
    tail = _tail_daemon_log(log)
    assert tail == [
        "line one",
        "line two",
        "three",
        "four",
        "five",
        "RuntimeError: CUDA GPU required",
    ]


def test_tail_daemon_log_missing_file_is_empty(tmp_path: Path) -> None:
    assert _tail_daemon_log(tmp_path / "absent.log") == []


def test_status_env_label_reads_the_executable() -> None:
    assert _status_env_label({"executable": "/venv/bin/python"}) == "/venv/bin/python"


def test_status_env_label_missing_is_explicit() -> None:
    assert _status_env_label(None) == "not reported by service"
    assert _status_env_label({}) == "not reported by service"


class TestRuntimeEnvClassifier:
    """Pure-path env classification: tool env, uvx ephemeral, project venv."""

    def test_a_receipt_marks_a_tool_environment(self, tmp_path: Path) -> None:
        """The receipt uv writes is what makes an environment a tool env.

        Guard assertion: detection used to require a parent directory named
        ``tools``, and uv nests its tool trees one level deeper than that, so
        a real tool environment classified as unrecognised unless the operator
        happened to have exported ``UV_TOOL_DIR``.
        """
        prefix = tmp_path / "uv" / "tools" / "versions" / "vaultspec-rag"
        prefix.mkdir(parents=True)
        assert classify_environment(prefix) is RuntimeEnvKind.OTHER
        (prefix / TOOL_RECEIPT_NAME).write_text("[tool]\n", encoding="utf-8")
        assert classify_environment(prefix) is RuntimeEnvKind.UV_TOOL

    def test_uvx_ephemeral_archive_v0_shape(self, tmp_path: Path) -> None:
        prefix = tmp_path / "uv" / "cache" / "archive-v0" / "AbC123xyz"
        prefix.mkdir(parents=True)
        assert classify_environment(prefix) is RuntimeEnvKind.UVX_EPHEMERAL

    def test_uv_tool_dir_override_wins(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        tool_root = tmp_path / "custom-tool-root"
        prefix = tool_root / "vaultspec-rag"
        prefix.mkdir(parents=True)
        monkeypatch.setenv("UV_TOOL_DIR", str(tool_root))
        assert classify_environment(prefix) is RuntimeEnvKind.UV_TOOL

    def test_uv_cache_dir_override_marks_ephemeral(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cache_root = tmp_path / "custom-cache"
        prefix = cache_root / "someenv"
        prefix.mkdir(parents=True)
        monkeypatch.setenv("UV_CACHE_DIR", str(cache_root))
        assert classify_environment(prefix) is RuntimeEnvKind.UVX_EPHEMERAL

    def test_project_venv_shape(self, tmp_path: Path) -> None:
        prefix = tmp_path / "myproject" / ".venv"
        prefix.mkdir(parents=True)
        assert classify_environment(prefix) is RuntimeEnvKind.PROJECT_VENV

    def test_unrecognized_is_other(self, tmp_path: Path) -> None:
        prefix = tmp_path / "somewhere" / "python-3.13"
        prefix.mkdir(parents=True)
        assert classify_environment(prefix) is RuntimeEnvKind.OTHER

    def test_interpreter_classification_walks_to_env_root(self, tmp_path: Path) -> None:
        root = tmp_path / "uv" / "tools" / "vaultspec-rag"
        scripts = root / "Scripts"
        scripts.mkdir(parents=True)
        (root / TOOL_RECEIPT_NAME).write_text("[tool]\n", encoding="utf-8")
        interpreter = scripts / "python.exe"
        interpreter.touch()
        assert (
            classify_environment(environment_root(interpreter))
            is RuntimeEnvKind.UV_TOOL
        )

    def test_interpreter_classification_posix_bin(self, tmp_path: Path) -> None:
        bin_dir = tmp_path / "cache" / "archive-v0" / "aBcDeF" / "bin"
        bin_dir.mkdir(parents=True)
        interpreter = bin_dir / "python"
        interpreter.touch()
        assert (
            classify_environment(environment_root(interpreter))
            is RuntimeEnvKind.UVX_EPHEMERAL
        )

    def test_every_kind_has_a_label(self) -> None:
        for kind in RuntimeEnvKind:
            assert kind.label


class TestRemediationCommands:
    """Every CUDA repair string derives from the one cu130 constant surface."""

    def test_escape_hatch_targets_the_interpreter_and_cu130_backend(self) -> None:
        cmd = inplace_cuda_command(r"C:\envs\tool\Scripts\python.exe")
        assert '--python "C:\\envs\\tool\\Scripts\\python.exe"' in cmd
        backend = CU130_INDEX_URL.rsplit("/", 1)[-1]
        assert f"--torch-backend={backend}" in cmd
        assert "--reinstall" in cmd
        assert cmd.endswith("torch")

    def test_platform_tag_derives_the_linux_machine(self) -> None:
        """The CUDA source is offered only where PyTorch publishes one.

        PyTorch publishes ``manylinux_2_28`` builds per machine architecture,
        so the machine is read from the host rather than assumed.
        """
        assert (
            published_wheel_platform_tag("linux", "aarch64") == "manylinux_2_28_aarch64"
        )
        assert (
            published_wheel_platform_tag("linux", "x86_64") == "manylinux_2_28_x86_64"
        )
        # Windows publishes one architecture, so the machine is consulted only
        # to confirm it is that one.
        assert published_wheel_platform_tag("win32", "AMD64") == "win_amd64"

    def test_a_platform_without_a_cuda_build_is_not_offered_the_index(self) -> None:
        """Guard assertion: the index resolves a CPU build for those hosts.

        The platform was read by family alone, so an ARM64 Windows machine
        and every macOS machine were handed a repair that cannot give them a
        GPU build - which reads to an operator as one they applied wrong.
        """
        assert published_wheel_platform_tag("win32", "ARM64") is None
        assert published_wheel_platform_tag("darwin", "arm64") is None
        assert published_wheel_platform_tag("linux", "armv7l") is None

    def test_an_unsupported_platform_is_refused_in_plain_words(self) -> None:
        """No command is offered where no accelerated build exists."""
        remediation = cuda_remediation(
            "/opt/env/bin/python", platform_name="win32", machine="ARM64"
        )

        assert remediation.kind is CudaRepairKind.NO_PUBLISHED_WHEEL
        assert not remediation.kind.repairable
        assert remediation.repair_commands == ()
        joined = "\n".join(remediation.steps)
        assert CU130_INDEX_URL not in joined
        assert "publishes no CUDA build" in joined

    def test_macos_is_pointed_at_metal_not_at_a_cuda_index(self) -> None:
        """Guard assertion: a cu130 source on macOS is a repair that cannot work."""
        remediation = cuda_remediation(
            "/opt/env/bin/python", platform_name="darwin", machine="arm64"
        )

        assert remediation.kind is CudaRepairKind.APPLE_METAL
        joined = "\n".join(remediation.steps)
        assert CU130_INDEX_URL not in joined
        assert "Metal" in joined


def _install_metadata(tmp_path: Path, distribution: str, version: str) -> None:
    """Record *distribution* as installed in the stand-in tool environment."""
    site = tmp_path / "vaultspec-rag" / "Lib" / "site-packages"
    site.mkdir(parents=True, exist_ok=True)
    (site / f"{distribution}-{version}.dist-info").mkdir(exist_ok=True)


def _tool_env(tmp_path: Path, receipt: str) -> str:
    """A tool environment carrying *receipt*, and the interpreter inside it."""
    root = tmp_path / "vaultspec-rag"
    (root / "Scripts").mkdir(parents=True, exist_ok=True)
    (root / TOOL_RECEIPT_NAME).write_text(receipt, encoding="utf-8")
    return str(root / "Scripts" / "python.exe")


_PLAIN_RECEIPT = '[tool]\nrequirements = [{ name = "vaultspec-rag" }]\n'

_DURABLE_RECEIPT = (
    '[tool]\nrequirements = [{ name = "vaultspec-rag" }]\n\n'
    "[tool.options]\n"
    f'index = [{{ url = "{CU130_INDEX_URL}", explicit = false }}]\n'
    f'index-strategy = "{CU130_INDEX_STRATEGY}"\n'
)


class TestTheReceiptCarriesTheCudaSource:
    """A tool installation stays a GPU host through its own receipt.

    Guard assertion: the shipped repair kept CUDA by pinning a direct wheel
    URL and the installed release into the receipt, which keeps the GPU build
    only by making the installation unable to move at all.
    """

    def test_the_repair_swaps_torch_first_and_records_the_index_after(
        self, tmp_path: Path
    ) -> None:
        """Two steps, in this order, and neither re-installs a launcher.

        Guard assertion: a ``uv tool install`` that changes any package
        re-installs the tool's entry-point launchers, cannot replace one that
        is running, and then removes the whole environment. The product's own
        consented run always holds a launcher, so the package change goes
        through uv's pip interface and the install that follows it has
        nothing left to change.
        """
        interpreter = _tool_env(
            tmp_path,
            '[tool]\nrequirements = [{ name = "vaultspec-rag", extras = ["gpu"] }]\n',
        )
        _install_metadata(tmp_path, "vaultspec_rag", "0.5.2")
        _install_metadata(tmp_path, "torch", "2.14.0+cpu")

        swap, receipt = tool_repair_commands(interpreter)

        assert swap.startswith("uv pip install ")
        assert f"--python {interpreter}" in swap or f'--python "{interpreter}"' in swap
        assert f"--index {CU130_INDEX_URL}" in swap
        assert f"--index-strategy {CU130_INDEX_STRATEGY}" in swap
        assert "--reinstall-package torch" in swap
        # The release already installed, so a damaged environment regains
        # what it lost without gaining a release nobody asked for.
        assert '"vaultspec-rag[gpu]==0.5.2"' in swap
        # The public release, because no index publishes a local build under
        # its local segment; which build answers is the index's decision.
        assert "torch==2.14.0" in swap
        assert "+cpu" not in swap

        assert receipt.startswith("uv tool install ")
        assert f"--index {CU130_INDEX_URL}" in receipt
        assert f"--index-strategy {CU130_INDEX_STRATEGY}" in receipt
        assert '"vaultspec-rag[gpu]"' in receipt
        assert "==" not in receipt

    def test_no_command_for_an_existing_environment_changes_a_package_by_tool_install(
        self, tmp_path: Path
    ) -> None:
        """Guard assertion: this is the shape that deletes the environment.

        `uv tool install` re-installs every entry-point launcher after any
        package change. On Windows it cannot replace a running one, and it
        removes the whole environment rather than leaving it half-written.
        Every flag below makes such an install change a package, so none of
        them may appear in a command the product runs or hands over for an
        environment that already exists.
        """
        forbidden = (
            "--upgrade",
            "--upgrade-package",
            "--reinstall",
            "--reinstall-package",
            "--force",
            "--with",
        )
        interpreter = _tool_env(tmp_path, _PLAIN_RECEIPT)
        _install_metadata(tmp_path, "vaultspec_rag", "0.5.2")
        _install_metadata(tmp_path, "torch", "2.14.0+cpu")
        remediation = cuda_remediation(
            interpreter,
            env_kind=RuntimeEnvKind.UV_TOOL,
            platform_name="win32",
            machine="AMD64",
        )

        offered = (
            *remediation.repair_commands,
            *remediation.upgrade_commands,
            *classify_tool_receipt(interpreter).fix(interpreter),
            *upgrade_commands_for_mode("tool", interpreter),
        )

        for command in offered:
            for line in command.splitlines():
                if not line.strip().startswith("uv tool install"):
                    continue
                assert not any(flag in line for flag in forbidden), line

    def test_the_python_request_names_the_target_environments_own_version(
        self, tmp_path: Path
    ) -> None:
        """Guard assertion: a mismatched request destroys the environment.

        uv reads a ``--python`` it does not recognise as the environment's
        own as a request for a different environment, and rebuilds wholesale:
        it removes the contents and then fails on whatever a running service
        holds, leaving nothing importable. The version therefore comes out of
        the target environment, never out of the process doing the asking.
        """
        interpreter = _tool_env(tmp_path, _PLAIN_RECEIPT)
        root = Path(interpreter).parent.parent
        (root / "pyvenv.cfg").write_text(
            f"home = {tmp_path / 'python' / 'cpython-3.14-windows'}\n"
            "implementation = CPython\n"
            "version_info = 3.14.6\n",
            encoding="utf-8",
        )

        assert environment_python_request(interpreter) == "3.14"
        assert "--python 3.14 " in tool_repair_commands(interpreter)[1]

    def test_an_environment_that_cannot_be_read_gets_no_python_request(
        self, tmp_path: Path
    ) -> None:
        """No request at all keeps the interpreter uv already has.

        Guessing one from the running process is what produced the mismatch
        that rebuilds the environment.
        """
        interpreter = _tool_env(tmp_path, _PLAIN_RECEIPT)

        assert environment_python_request(interpreter) is None
        assert "--python" not in tool_repair_commands(interpreter)[1]

    def test_a_damaged_environment_is_named_without_a_release(
        self, tmp_path: Path
    ) -> None:
        """An environment that lost its metadata is not given a guessed one.

        Guard assertion: naming the asking process's own release here would
        install that release into someone else's environment.
        """
        interpreter = _tool_env(tmp_path, _PLAIN_RECEIPT)

        swap = tool_repair_commands(interpreter)[0]

        assert swap.endswith("vaultspec-rag")
        assert "==" not in swap

    def test_a_receipt_with_both_options_and_no_pin_is_durable(
        self, tmp_path: Path
    ) -> None:
        interpreter = _tool_env(tmp_path, _DURABLE_RECEIPT)

        verdict = classify_tool_receipt(interpreter)

        assert verdict is ToolReceiptVerdict.DURABLE
        assert verdict.durable
        assert verdict.fix(interpreter) == ()

    def test_a_version_pin_is_named_as_the_reason_upgrades_do_nothing(
        self, tmp_path: Path
    ) -> None:
        interpreter = _tool_env(
            tmp_path,
            '[tool]\nrequirements = [{ name = "vaultspec-rag", '
            'specifier = "==0.4.35" }]\n\n'
            "[tool.options]\n"
            f'index = [{{ url = "{CU130_INDEX_URL}" }}]\n'
            f'index-strategy = "{CU130_INDEX_STRATEGY}"\n',
        )

        verdict = classify_tool_receipt(interpreter)

        assert verdict is ToolReceiptVerdict.VERSION_PINNED
        assert not verdict.durable
        assert verdict.fix(interpreter) == tool_repair_commands(interpreter)

    def test_a_pinned_torch_wheel_is_named_as_its_own_defect(
        self, tmp_path: Path
    ) -> None:
        interpreter = _tool_env(
            tmp_path,
            '[tool]\nrequirements = [\n  { name = "vaultspec-rag" },\n'
            '  { name = "torch", url = "https://example.test/torch.whl" },\n]\n',
        )

        assert (
            classify_tool_receipt(interpreter) is ToolReceiptVerdict.TORCH_WHEEL_PINNED
        )

    def test_a_torch_pin_counts_however_it_was_recorded(self, tmp_path: Path) -> None:
        """Guard assertion: a pin is a pin whichever key uv wrote it under.

        uv records a direct requirement under ``url`` for an http one and
        ``path`` for a local file, and an exact specifier freezes the build
        just as hard. Reading only the first called the other two durable,
        so an installation that can never resolve a new torch reported that
        upgrades would keep its GPU build.
        """
        wheel_path = (tmp_path / "wheels" / "torch.whl").as_posix()
        for recorded in (
            f'{{ name = "torch", path = "{wheel_path}" }}',
            '{ name = "torch", specifier = "==2.14.0+cu130" }',
        ):
            interpreter = _tool_env(
                tmp_path,
                "[tool]\nrequirements = [\n"
                '  { name = "vaultspec-rag" },\n'
                f"  {recorded},\n]\n",
            )

            assert (
                classify_tool_receipt(interpreter)
                is ToolReceiptVerdict.TORCH_WHEEL_PINNED
            ), recorded

    def test_a_receipt_without_the_options_will_resolve_a_cpu_build(
        self, tmp_path: Path
    ) -> None:
        interpreter = _tool_env(
            tmp_path, '[tool]\nrequirements = [{ name = "vaultspec-rag" }]\n'
        )

        assert classify_tool_receipt(interpreter) is ToolReceiptVerdict.NO_CUDA_SOURCE

    def test_the_default_index_strategy_does_not_count_as_a_cuda_source(
        self, tmp_path: Path
    ) -> None:
        """Guard assertion: the index alone leaves the request unsatisfiable.

        The CUDA mirror carries packages this one depends on at versions it
        cannot use, and uv's default strategy forbids falling through to
        PyPI, so an installation recorded that way resolves nothing at all.
        """
        interpreter = _tool_env(
            tmp_path,
            '[tool]\nrequirements = [{ name = "vaultspec-rag" }]\n\n'
            "[tool.options]\n"
            f'index = [{{ url = "{CU130_INDEX_URL}" }}]\n',
        )

        assert classify_tool_receipt(interpreter) is ToolReceiptVerdict.NO_CUDA_SOURCE

    def test_an_unreadable_receipt_is_not_read_as_durable(self, tmp_path: Path) -> None:
        """Absence of evidence is not evidence of a working upgrade path."""
        root = tmp_path / "vaultspec-rag"
        (root / "Scripts").mkdir(parents=True)

        verdict = classify_tool_receipt(str(root / "Scripts" / "python.exe"))

        assert verdict is ToolReceiptVerdict.UNREADABLE
        assert not verdict.durable

    def test_every_verdict_has_a_label(self) -> None:
        for verdict in ToolReceiptVerdict:
            assert verdict.label


class TestUpgradeCommands:
    """A tool installation is told how to take a new release, and to restart."""

    def test_a_durable_receipt_upgrades_with_uvs_own_verb_then_restarts(
        self, tmp_path: Path
    ) -> None:
        """Guard assertion: an upgraded host keeps serving the old release.

        uv replaces the installed package while the daemon keeps running the
        code it imported at startup, so an upgrade that says nothing about
        restarting leaves a client refusing a service on the old release.
        """
        interpreter = _tool_env(tmp_path, _DURABLE_RECEIPT)

        upgrade, restart = tool_upgrade_commands(interpreter)

        assert upgrade == "uv tool upgrade vaultspec-rag"
        assert "server stop" in restart
        assert "server start" in restart

    def test_the_repair_block_offers_the_verb_that_takes_a_release(
        self, tmp_path: Path
    ) -> None:
        """Guard assertion: the receipt install takes no release at all.

        The later-upgrade line was the first element of this installation's
        current upgrade sequence, which for a receipt carrying no CUDA source
        is the options-only install. An operator following it changes
        nothing and stays on the release they wanted to leave. The repair
        itself makes the receipt durable, so the honest command afterwards is
        uv's own verb.
        """
        interpreter = _tool_env(tmp_path, _PLAIN_RECEIPT)

        remediation = cuda_remediation(
            interpreter,
            env_kind=RuntimeEnvKind.UV_TOOL,
            platform_name="win32",
            machine="AMD64",
        )

        later = [step for step in remediation.steps if "Take a newer release" in step]
        assert later == [
            f"Take a newer release later with: {release_upgrade_command()}"
        ]
        assert "uv tool install" not in later[0]

    def test_a_receipt_that_is_not_durable_upgrades_through_the_repair(
        self, tmp_path: Path
    ) -> None:
        """A bare upgrade of such an installation drops the GPU build.

        Guard assertion: the previous form reached for
        `uv tool install --upgrade`, which re-installs the launchers and
        removes the environment while one of them runs. The receipt is
        recorded first instead, by an install that changes no package, and
        uv's own verb then does the upgrading.
        """
        interpreter = _tool_env(tmp_path, _PLAIN_RECEIPT)

        record, upgrade, restart = tool_upgrade_commands(interpreter)

        assert record.startswith("uv tool install ")
        assert f"--index {CU130_INDEX_URL}" in record
        assert "--upgrade" not in record
        assert upgrade == "uv tool upgrade vaultspec-rag"
        assert "server stop" in restart

    def test_a_project_installation_upgrades_through_its_lockfile(self) -> None:
        """Only a standalone tool needs the receipt-aware form."""
        for mode in ("dependency", "dev"):
            assert upgrade_commands_for_mode(mode, sys.executable) == (
                "uv sync --upgrade-package vaultspec-rag",
            )


def _durable_command_for(interpreter: str) -> str:
    """The request the one builder offers an ephemeral environment."""
    return cuda_remediation(
        interpreter, env_kind=RuntimeEnvKind.UVX_EPHEMERAL
    ).repair_commands[-1]


class TestEphemeralEnvWarning:
    """server start's uvx-ephemeral warning fires only for the cache env."""

    def test_warns_for_an_ephemeral_interpreter(self, tmp_path: Path) -> None:
        scripts = tmp_path / "cache" / "archive-v0" / "xYz987" / "Scripts"
        scripts.mkdir(parents=True)
        interpreter = scripts / "python.exe"
        interpreter.touch()
        lines = _ephemeral_env_warning(str(interpreter))
        joined = "\n".join(lines)
        assert "EPHEMERAL" in joined
        assert "not the installed tool" in joined
        assert _durable_command_for(str(interpreter)) in joined
        assert str(interpreter) in joined

    def test_silent_for_a_tool_env_interpreter(self, tmp_path: Path) -> None:
        scripts = tmp_path / "uv" / "tools" / "vaultspec-rag" / "Scripts"
        scripts.mkdir(parents=True)
        interpreter = scripts / "python.exe"
        interpreter.touch()
        assert _ephemeral_env_warning(str(interpreter)) == ()


class TestCallerEphemeralWarning:
    """The attach paths warn about the caller's own env, not a daemon's.

    ``server start`` against a live service returns ``already_running`` before
    any daemon interpreter is resolved, so the daemon-side warning cannot fire.
    An operator invoking from a uvx cache env still walks into the
    forced-reinstall trap, and for a long-lived daemon that attach outcome is
    the common one - so the caller env is warned about on its own terms.
    """

    def test_warns_for_an_ephemeral_caller(self, tmp_path: Path) -> None:
        scripts = tmp_path / "cache" / "archive-v0" / "aB3dEf" / "Scripts"
        scripts.mkdir(parents=True)
        interpreter = scripts / "python.exe"
        interpreter.touch()
        lines = _caller_ephemeral_warning(str(interpreter))
        joined = "\n".join(lines)
        assert "EPHEMERAL" in joined
        assert "not the installed tool" in joined
        assert str(interpreter) in joined
        # The remediation must stay the single-sourced durable command, so the
        # attach path cannot drift from the spawn path's guidance.
        assert _durable_command_for(str(interpreter)) in joined

    def test_names_the_caller_not_the_service(self, tmp_path: Path) -> None:
        scripts = tmp_path / "cache" / "archive-v0" / "aB3dEf" / "Scripts"
        scripts.mkdir(parents=True)
        interpreter = scripts / "python.exe"
        interpreter.touch()
        joined = "\n".join(_caller_ephemeral_warning(str(interpreter)))
        # The running service was started from some other env; claiming its
        # interpreter is ephemeral would be false on the attach path.
        assert "this command is running from" in joined
        assert "service interpreter is" not in joined

    def test_silent_for_a_tool_env_caller(self, tmp_path: Path) -> None:
        scripts = tmp_path / "uv" / "tools" / "vaultspec-rag" / "Scripts"
        scripts.mkdir(parents=True)
        interpreter = scripts / "python.exe"
        interpreter.touch()
        assert _caller_ephemeral_warning(str(interpreter)) == ()

    def test_silent_for_a_project_venv_caller(self, tmp_path: Path) -> None:
        scripts = tmp_path / "myproject" / ".venv" / "Scripts"
        scripts.mkdir(parents=True)
        interpreter = scripts / "python.exe"
        interpreter.touch()
        assert _caller_ephemeral_warning(str(interpreter)) == ()
