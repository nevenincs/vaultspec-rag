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
    tool_repair_command,
    tool_upgrade_commands,
    upgrade_command_for_mode,
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
        "line one\n\n  \nline two\nRuntimeError: CUDA GPU required\n",
        encoding="utf-8",
    )
    tail = _tail_daemon_log(log, max_lines=2)
    assert tail == ["line two", "RuntimeError: CUDA GPU required"]


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
        assert remediation.repair_command == ""
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


def _tool_env(tmp_path: Path, receipt: str) -> str:
    """A tool environment carrying *receipt*, and the interpreter inside it."""
    root = tmp_path / "vaultspec-rag"
    (root / "Scripts").mkdir(parents=True)
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

    def test_the_repair_records_the_index_and_changes_torch_only(
        self, tmp_path: Path
    ) -> None:
        """The command uv re-applies on every upgrade is what carries CUDA.

        Without ``--upgrade-package torch`` uv rewrites the receipt and keeps
        the CPU build it already has, because that build still satisfies the
        requirement; with ``--force`` it would replace the whole environment,
        which is the destruction this cycle exists to avoid.
        """
        interpreter = _tool_env(
            tmp_path,
            '[tool]\nrequirements = [{ name = "vaultspec-rag", extras = ["gpu"] }]\n',
        )

        command = tool_repair_command(interpreter)

        assert f"--index {CU130_INDEX_URL}" in command
        assert f"--index-strategy {CU130_INDEX_STRATEGY}" in command
        assert "--upgrade-package torch" in command
        assert '"vaultspec-rag[gpu]"' in command
        assert "--force" not in command
        assert "==" not in command
        assert "--with" not in command

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
            "home = C:/python/cpython-3.14-windows\n"
            "implementation = CPython\n"
            "version_info = 3.14.6\n",
            encoding="utf-8",
        )

        assert environment_python_request(interpreter) == "3.14"
        assert "--python 3.14 " in tool_repair_command(interpreter)

    def test_an_environment_that_cannot_be_read_gets_no_python_request(
        self, tmp_path: Path
    ) -> None:
        """No request at all keeps the interpreter uv already has.

        Guessing one from the running process is what produced the mismatch
        that rebuilds the environment.
        """
        interpreter = _tool_env(tmp_path, _PLAIN_RECEIPT)

        assert environment_python_request(interpreter) is None
        assert "--python" not in tool_repair_command(interpreter)

    def test_a_free_threaded_environment_keeps_its_t_suffix(
        self, tmp_path: Path
    ) -> None:
        """A free-threaded build is a different interpreter to uv.

        Guard assertion: the version alone reads the same for both builds, so
        a request derived from it names the GIL interpreter and uv rebuilds.
        """
        interpreter = _tool_env(tmp_path, _PLAIN_RECEIPT)
        root = Path(interpreter).parent.parent
        (root / "pyvenv.cfg").write_text(
            "home = /opt/uv/python/cpython-3.14.6+freethreaded-linux\n"
            "version_info = 3.14.6\n",
            encoding="utf-8",
        )

        assert environment_python_request(interpreter) == "3.14t"

    def test_a_receipt_with_both_options_and_no_pin_is_durable(
        self, tmp_path: Path
    ) -> None:
        interpreter = _tool_env(tmp_path, _DURABLE_RECEIPT)

        verdict = classify_tool_receipt(interpreter)

        assert verdict is ToolReceiptVerdict.DURABLE
        assert verdict.durable
        assert verdict.fix(interpreter) is None

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
        assert verdict.fix(interpreter) == tool_repair_command(interpreter)

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

    def test_a_receipt_that_is_not_durable_upgrades_through_the_repair(
        self, tmp_path: Path
    ) -> None:
        """A bare upgrade of such an installation drops the GPU build."""
        interpreter = _tool_env(
            tmp_path, '[tool]\nrequirements = [{ name = "vaultspec-rag" }]\n'
        )

        upgrade = tool_upgrade_commands(interpreter)[0]

        assert upgrade == tool_repair_command(interpreter, upgrade=True)
        assert "--upgrade" in upgrade
        assert f"--index {CU130_INDEX_URL}" in upgrade

    def test_a_project_installation_upgrades_through_its_lockfile(self) -> None:
        """Only a standalone tool needs the receipt-aware form."""
        for mode in ("dependency", "dev"):
            assert (
                upgrade_command_for_mode(mode, sys.executable)
                == "uv sync --upgrade-package vaultspec-rag"
            )


def _durable_command_for(interpreter: str) -> str:
    """The request the one builder offers an ephemeral environment."""
    return cuda_remediation(
        interpreter, env_kind=RuntimeEnvKind.UVX_EPHEMERAL
    ).repair_command


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
