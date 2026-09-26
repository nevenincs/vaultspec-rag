"""Service<->python-env hardening: the start-failure log tail, the status env
label, and the environment classifier.

All real-behavior, no mocks: the log tail against a real temp file, and the env
label against plain dicts.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from ..cli._service_start import (
    _caller_ephemeral_warning,
    _ephemeral_env_warning,
    _tail_daemon_log,
)
from ..cli._status_labels import _status_env_label
from ..operator_state._provisioning import (
    HOLDER_PRECONDITION,
    CudaRepairKind,
    _wheel_torch_version,
    cuda_remediation,
    inplace_cuda_command,
    published_wheel_platform_tag,
    tool_cuda_install_spec,
    tool_upgrade_command,
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

    @pytest.mark.torch
    def test_durable_command_pins_a_cu130_wheel_via_with(self) -> None:
        import importlib.metadata

        from packaging.version import Version

        spec = tool_cuda_install_spec()
        assert spec is not None
        cmd = spec.command
        assert CU130_INDEX_URL in cmd
        assert "uv tool install" in cmd
        assert "vaultspec-rag[gpu,mcp]" in cmd
        # --index is NOT recorded in uv tool receipts (verified on uv 0.11.x),
        # so the durable form must be the --with direct wheel URL.
        assert "--with" in cmd
        assert "--index" not in cmd
        # Both tags track the RUNNING interpreter — a hardcoded tag hands a
        # 3.13 wheel to a 3.14 install and uv rejects it on a tag mismatch.
        # Compared against packaging rather than a re-derived f-string, so the
        # assertion cannot restate the same mistake the implementation makes.
        from packaging.tags import cpython_tags

        tag = next(iter(cpython_tags()))
        # The version tracks the torch already installed in this env (the CPU
        # wheel being replaced), read from distribution metadata - an
        # independent source from whatever the implementation consults.
        torch_version = Version(importlib.metadata.version("torch")).base_version
        assert f"torch-{torch_version}%2Bcu130-{tag.interpreter}-{tag.abi}-" in cmd
        # `uv tool install --force` rebuilds the env with uv's DEFAULT python
        # request, not the interpreter that printed the command, so the wheel
        # pin must travel with a matching --python request (uv records it in
        # the receipt). Derived from sys.version_info here - an independent
        # source from the packaging tag the implementation parses.
        assert f"--python {sys.version_info[0]}.{sys.version_info[1]}" in cmd

    def test_wheel_version_strips_the_local_suffix(self) -> None:
        """The wheel version follows the env's torch, not a baked constant.

        An env whose torch is older than the workspace pin must be offered
        the same release it already resolved - the cu130 flavour of a version
        the index may no longer pair with this interpreter otherwise. The
        local ``+cpu`` suffix must be stripped: the index names ``+cu130``.
        """
        assert _wheel_torch_version("2.99.1+cpu") == "2.99.1"
        assert _wheel_torch_version("2.9.0") == "2.9.0"

    def test_wheel_version_falls_back_when_torch_is_absent(self) -> None:
        """With no torch installed the pinned fallback version is offered."""
        from ..torch_config._constants import TORCH_TOOL_PIN_VERSION

        assert _wheel_torch_version(None) == TORCH_TOOL_PIN_VERSION
        assert _wheel_torch_version("not-a-version") == TORCH_TOOL_PIN_VERSION

    def test_platform_tag_derives_the_linux_machine(self) -> None:
        """An aarch64 Linux host is offered the aarch64 wheel, not x86_64.

        The platform half of the wheel name was a hardcoded x86_64 string;
        PyTorch publishes ``manylinux_2_28`` wheels per machine architecture,
        so the machine must be read from the host.
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

    def test_a_platform_without_a_cuda_wheel_has_no_tag(self) -> None:
        """Guard assertion: an invented tag names a URL the index refuses.

        The tag was derived from the platform family alone, so an ARM64
        Windows machine and every macOS machine were handed a wheel URL that
        returns an error - which reads to an operator as a repair they applied
        wrong rather than one that does not exist.
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
        assert remediation.durable_command == ""
        assert remediation.immediate_command == ""
        joined = "\n".join(remediation.steps)
        assert CU130_INDEX_URL not in joined
        assert "publishes no CUDA build" in joined

    def test_macos_is_pointed_at_metal_not_at_a_cuda_wheel(self) -> None:
        """Guard assertion: a cu130 URL on macOS is a repair that cannot work."""
        remediation = cuda_remediation(
            "/opt/env/bin/python", platform_name="darwin", machine="arm64"
        )

        assert remediation.kind is CudaRepairKind.APPLE_METAL
        joined = "\n".join(remediation.steps)
        assert CU130_INDEX_URL not in joined
        assert "Metal" in joined

    def test_a_tool_environment_gets_both_repairs_and_the_precondition(
        self, tmp_path: Path
    ) -> None:
        """The immediate repair and the durable receipt fix, together, once.

        Guard assertion: one field run printed three different repair commands
        from three surfaces, because each surface built its own.
        """
        interpreter = tmp_path / "Scripts" / "python.exe"
        interpreter.parent.mkdir()

        remediation = cuda_remediation(
            str(interpreter),
            env_kind=RuntimeEnvKind.UV_TOOL,
            platform_name="win32",
            machine="AMD64",
        )

        assert remediation.kind is CudaRepairKind.TOOL_ENVIRONMENT
        assert remediation.immediate_command == inplace_cuda_command(str(interpreter))
        assert remediation.spec is not None
        assert remediation.durable_command == remediation.spec.command
        joined = "\n".join(remediation.steps)
        assert remediation.immediate_command in joined
        assert remediation.durable_command in joined
        assert HOLDER_PRECONDITION in remediation.steps

    def test_command_names_the_free_threaded_abi(self) -> None:
        """A free-threaded host must get the ``t`` wheel, not the GIL one.

        The interpreter and ABI tags differ only on a free-threaded build
        (``cp314-cp314t``), and ``sys.version_info`` is ``(3, 14)`` for both
        builds, so an implementation that derives one tag and uses it twice
        emits ``cp314-cp314`` here and uv refuses it on a tag mismatch. CI runs
        a GIL interpreter, where the two tags are equal and the bug is
        invisible, so the free-threaded tag is passed explicitly.
        """
        from packaging.tags import Tag

        spec = tool_cuda_install_spec(
            torch_version="2.9.0",
            tag=Tag("cp314", "cp314t", "win_amd64"),
            platform_tag="win_amd64",
        )
        assert spec is not None
        cmd = spec.command

        assert "-cp314-cp314t-" in cmd, (
            f"free-threaded host must be offered the cp314t wheel; command was: {cmd}"
        )
        assert "-cp314-cp314-" not in cmd, (
            "the GIL wheel was named for a free-threaded interpreter"
        )
        # The --python request must come from the SAME tag as the wheel -
        # otherwise install resolves on an interpreter the pinned wheel cannot
        # satisfy. `uv tool install --force` rebuilds the env with uv's DEFAULT
        # python request, not the interpreter that printed the command, so the
        # pin only travels if the request travels with it.
        assert "--python 3.14t " in cmd, (
            f"--python request must name the free-threaded interpreter; was: {cmd}"
        )

    def test_command_names_the_gil_interpreter_without_the_t_suffix(self) -> None:
        """The ``t`` suffix is the free-threaded signal, not decoration.

        Pairs with the free-threaded case: an implementation that always
        appends ``t`` would pass that one and fail here.
        """
        from packaging.tags import Tag

        spec = tool_cuda_install_spec(
            torch_version="2.9.0",
            tag=Tag("cp313", "cp313", "win_amd64"),
            platform_tag="manylinux_2_28_aarch64",
        )
        assert spec is not None
        cmd = spec.command

        assert "--python 3.13 " in cmd
        assert "-cp313-cp313-manylinux_2_28_aarch64.whl" in cmd
        assert "3.13t" not in cmd


class TestUpgradeCommands:
    """A pinned tool installation is told how to actually take a new release."""

    def test_the_upgrade_keeps_the_extras_and_the_wheel_and_asks_for_latest(
        self, tmp_path: Path
    ) -> None:
        """Guard assertion: `uv tool upgrade` is a no-op on a pinned tool.

        uv records the exact version the CUDA repair asks for, and answers a
        later upgrade with "nothing to upgrade", naming a re-install at
        ``@latest`` itself. Dropping the recorded wheel or the extras from
        that re-install undoes the GPU build the repair just established.
        """
        root = tmp_path / "vaultspec-rag"
        (root / "Scripts").mkdir(parents=True)
        wheel = f"{CU130_INDEX_URL}/torch-2.14.0%2Bcu130-cp313-cp313-win_amd64.whl"
        (root / TOOL_RECEIPT_NAME).write_text(
            "[tool]\nrequirements = [\n"
            '  { name = "vaultspec-rag", extras = ["gpu", "mcp"], '
            'specifier = "==0.5.2" },\n'
            f'  {{ name = "torch", url = "{wheel}" }},\n'
            "]\n",
            encoding="utf-8",
        )

        command = tool_upgrade_command(str(root / "Scripts" / "python.exe"))

        assert "uv tool install --force" in command
        assert '"vaultspec-rag[gpu,mcp]@latest"' in command
        assert "==" not in command
        assert f'"torch @ {wheel}"' in command

    def test_an_unpinned_tool_environment_still_gets_the_reinstall_form(
        self, tmp_path: Path
    ) -> None:
        """No receipt means no recorded wheel, and no invented one."""
        root = tmp_path / "vaultspec-rag"
        (root / "Scripts").mkdir(parents=True)

        command = tool_upgrade_command(str(root / "Scripts" / "python.exe"))

        assert '"vaultspec-rag[gpu,mcp]@latest"' in command
        assert "--with" not in command

    def test_a_project_installation_upgrades_through_its_lockfile(self) -> None:
        """Only a standalone tool needs the receipt-carrying re-installation."""
        for mode in ("dependency", "dev"):
            assert (
                upgrade_command_for_mode(mode, sys.executable)
                == "uv sync --upgrade-package vaultspec-rag"
            )

    def test_a_pinned_repair_discloses_the_pin_and_names_the_upgrade(
        self, tmp_path: Path
    ) -> None:
        """The repair says it pins, and what to run instead of the no-op.

        Guard assertion: the repair pins the installed version by decision,
        and nothing told the operator that their usual upgrade command would
        silently stop working.
        """
        root = tmp_path / "vaultspec-rag"
        (root / "Scripts").mkdir(parents=True)
        (root / TOOL_RECEIPT_NAME).write_text(
            '[tool]\nrequirements = [{ name = "vaultspec-rag", extras = ["gpu"] }]\n',
            encoding="utf-8",
        )

        remediation = cuda_remediation(
            str(root / "Scripts" / "python.exe"),
            env_kind=RuntimeEnvKind.UV_TOOL,
            platform_name="win32",
            machine="AMD64",
        )

        pinned = [step for step in remediation.steps if "pins the release" in step]
        assert pinned, "a pinned repair must say that it pins the release"
        pin_step = pinned[0]
        assert "uv tool upgrade" in pin_step
        assert remediation.upgrade_command in pin_step
        assert "@latest" in remediation.upgrade_command
        assert "==" in remediation.durable_command


def _durable_command_for(interpreter: str) -> str:
    """The durable request the one builder offers an ephemeral environment."""
    return cuda_remediation(
        interpreter, env_kind=RuntimeEnvKind.UVX_EPHEMERAL
    ).durable_command


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
