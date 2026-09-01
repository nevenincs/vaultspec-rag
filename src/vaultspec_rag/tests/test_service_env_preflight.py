"""Service<->python-env hardening: the daemon-interpreter pre-flight, the
start-failure log tail, and the status env label.

All real-behavior, no mocks: the pre-flight is exercised against actual
interpreters (the current one, and a path that does not exist), the log tail
against a real temp file, and the env label against plain dicts.
"""

from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from ..cli._gpu_errors import (
    RuntimeEnvKind,
    classify_interpreter_env,
    classify_runtime_env,
    durable_tool_install_command,
    gpu_escape_hatch_command,
)
from ..cli._process import _probe_daemon_cuda
from ..cli._service_start import (
    _caller_ephemeral_warning,
    _ephemeral_env_warning,
    _tail_daemon_log,
)
from ..cli._status_labels import _status_env_label
from ..commands._tool_torch import (
    _wheel_platform_tag,
    _wheel_torch_version,
    tool_cuda_install_spec,
)
from ..torch_config._constants import CU130_INDEX_URL

pytestmark = [pytest.mark.unit]

# Independent torch/cuda truth for an interpreter, evaluated in its OWN
# subprocess so this (torch-free) test process never imports torch - the same
# discipline the probe itself follows. Exit 0 == working CUDA torch.
_TRUTH = (
    "import importlib.util, sys\n"
    "if importlib.util.find_spec('torch') is None:\n"
    "    sys.exit(3)\n"
    "import torch\n"
    "sys.exit(0 if torch.cuda.is_available() else 1)\n"
)


def test_probe_agrees_with_independent_truth_for_the_current_interpreter() -> None:
    """The probe verdict matches an independent subprocess truth.

    Both the probe and the truth-check run in subprocesses, so this test process
    never imports torch (importing torch in-process is exactly what the probe
    avoids). A working CUDA torch must yield ``None``; anything else must yield a
    blocking verdict.
    """
    truth = subprocess.run(
        [sys.executable, "-c", _TRUTH],
        capture_output=True,
        timeout=120,
        check=False,
    ).returncode
    result = _probe_daemon_cuda(sys.executable)
    if truth == 0:
        assert result is None
    else:
        assert result is not None
        blocking, reason = result
        assert blocking is True
        assert reason


def test_probe_missing_interpreter_blocks_with_a_clear_reason() -> None:
    result = _probe_daemon_cuda("this-interpreter-does-not-exist-xyz")
    assert result is not None
    blocking, reason = result
    assert blocking is True
    assert "does not exist" in reason


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

    def test_uv_tool_env_windows_shape(self, tmp_path: Path) -> None:
        prefix = tmp_path / "AppData" / "Roaming" / "uv" / "tools" / "vaultspec-rag"
        prefix.mkdir(parents=True)
        assert classify_runtime_env(prefix) is RuntimeEnvKind.UV_TOOL

    def test_uvx_ephemeral_archive_v0_shape(self, tmp_path: Path) -> None:
        prefix = tmp_path / "uv" / "cache" / "archive-v0" / "AbC123xyz"
        prefix.mkdir(parents=True)
        assert classify_runtime_env(prefix) is RuntimeEnvKind.UVX_EPHEMERAL

    def test_uv_tool_dir_override_wins(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        tool_root = tmp_path / "custom-tool-root"
        prefix = tool_root / "vaultspec-rag"
        prefix.mkdir(parents=True)
        monkeypatch.setenv("UV_TOOL_DIR", str(tool_root))
        assert classify_runtime_env(prefix) is RuntimeEnvKind.UV_TOOL

    def test_uv_cache_dir_override_marks_ephemeral(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cache_root = tmp_path / "custom-cache"
        prefix = cache_root / "someenv"
        prefix.mkdir(parents=True)
        monkeypatch.setenv("UV_CACHE_DIR", str(cache_root))
        assert classify_runtime_env(prefix) is RuntimeEnvKind.UVX_EPHEMERAL

    def test_project_venv_shape(self, tmp_path: Path) -> None:
        prefix = tmp_path / "myproject" / ".venv"
        prefix.mkdir(parents=True)
        assert classify_runtime_env(prefix) is RuntimeEnvKind.PROJECT_VENV

    def test_unrecognized_is_other(self, tmp_path: Path) -> None:
        prefix = tmp_path / "somewhere" / "python-3.13"
        prefix.mkdir(parents=True)
        assert classify_runtime_env(prefix) is RuntimeEnvKind.OTHER

    def test_interpreter_classification_walks_to_env_root(self, tmp_path: Path) -> None:
        scripts = tmp_path / "uv" / "tools" / "vaultspec-rag" / "Scripts"
        scripts.mkdir(parents=True)
        interpreter = scripts / "python.exe"
        interpreter.touch()
        assert classify_interpreter_env(interpreter) is RuntimeEnvKind.UV_TOOL

    def test_interpreter_classification_posix_bin(self, tmp_path: Path) -> None:
        bin_dir = tmp_path / "cache" / "archive-v0" / "aBcDeF" / "bin"
        bin_dir.mkdir(parents=True)
        interpreter = bin_dir / "python"
        interpreter.touch()
        assert classify_interpreter_env(interpreter) is RuntimeEnvKind.UVX_EPHEMERAL

    def test_every_kind_has_a_label(self) -> None:
        for kind in RuntimeEnvKind:
            assert kind.label


class TestRemediationCommands:
    """The two remediation strings derive from the one cu130 constant surface."""

    def test_escape_hatch_targets_the_interpreter_and_cu130_backend(self) -> None:
        cmd = gpu_escape_hatch_command(r"C:\envs\tool\Scripts\python.exe")
        assert '--python "C:\\envs\\tool\\Scripts\\python.exe"' in cmd
        backend = CU130_INDEX_URL.rsplit("/", 1)[-1]
        assert f"--torch-backend={backend}" in cmd
        assert "--reinstall" in cmd
        assert cmd.endswith("torch")

    def test_durable_command_pins_a_cu130_wheel_via_with(self) -> None:
        import importlib.metadata

        from packaging.version import Version

        cmd = durable_tool_install_command()
        assert CU130_INDEX_URL in cmd
        assert "uv tool install" in cmd
        assert "vaultspec-rag[mcp]" in cmd
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
        assert _wheel_platform_tag("linux", "aarch64") == "manylinux_2_28_aarch64"
        assert _wheel_platform_tag("linux", "x86_64") == "manylinux_2_28_x86_64"
        # Windows publishes one architecture, so the machine is not consulted.
        assert _wheel_platform_tag("win32", "AMD64") == "win_amd64"

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

        cmd = tool_cuda_install_spec(
            torch_version="2.9.0",
            tag=Tag("cp314", "cp314t", "win_amd64"),
            platform_tag="win_amd64",
        ).command

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

        cmd = tool_cuda_install_spec(
            torch_version="2.9.0",
            tag=Tag("cp313", "cp313", "win_amd64"),
            platform_tag="manylinux_2_28_aarch64",
        ).command

        assert "--python 3.13 " in cmd
        assert "-cp313-cp313-manylinux_2_28_aarch64.whl" in cmd
        assert "3.13t" not in cmd


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
        assert durable_tool_install_command() in joined
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
        assert durable_tool_install_command() in joined

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
