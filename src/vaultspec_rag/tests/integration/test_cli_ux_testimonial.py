"""Operator-persona testimonial integration tests for the CLI (W03.P08.S15).

Three operator personas each run a scripted real CLI sequence using
``typer.testing.CliRunner`` (for workspace-free commands) and the
``live_service`` fixture (for daemon-bound commands).  Every observation
is recorded as a structured dict and asserted at the end.  No mocks,
patches, monkeypatches, or skips.

Personas
--------
- ``TestFirstTimeIndexer`` — discovers the CLI via ``--help`` and ``status``.
- ``TestSearchPowerUser``  — exercises ``search --help`` and a live code search.
- ``TestServiceOperator``  — exercises the flattened ``server <cmd>`` lifecycle
  over a running daemon and asserts ``server service`` is no longer valid.
"""

from __future__ import annotations

import typing
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from ...cli import app

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import TempPathFactory

pytestmark = [pytest.mark.integration]

runner = CliRunner()

# Developer tokens that must never appear in operator-facing --help output.
_FORBIDDEN_HELP_TOKENS = ("Args:", "Raises:", "CLIState", " ctx ")


@dataclass
class _Observation:
    """One scripted CLI step in a persona's journey."""

    command: list[str]
    exit_code: int
    output: str
    friction: str = ""  # operator note on anything surprising


# ---------------------------------------------------------------------------
# Persona 1: First-time indexer
# ---------------------------------------------------------------------------


def _observe_first_time_indexer(tmp_path: Path) -> list[_Observation]:
    from ._helpers import _service_env

    (tmp_path / ".vault").mkdir()
    (tmp_path / ".vaultspec").mkdir()

    observations: list[_Observation] = []
    for command in (["--help"], ["index", "--help"]):
        result = runner.invoke(app, command)
        observations.append(
            _Observation(
                command=command,
                exit_code=result.exit_code,
                output=result.output,
                friction="" if result.exit_code == 0 else "unexpected non-zero exit",
            )
        )

    status_command = ["--target", str(tmp_path), "status"]
    with _service_env(tmp_path):
        result = runner.invoke(app, status_command)
    observations.append(
        _Observation(
            command=status_command,
            exit_code=result.exit_code,
            output=result.output,
            friction="" if result.exit_code == 0 else "unexpected non-zero exit",
        )
    )
    return observations


def _assert_observations_succeeded(observations: list[_Observation]) -> None:
    for obs in observations:
        assert obs.exit_code == 0, (
            f"Command {obs.command!r} exited {obs.exit_code}.\n"
            f"friction: {obs.friction!r}\n"
            f"output:\n{obs.output}"
        )


def _assert_help_observations_clean(observations: list[_Observation]) -> None:
    help_obs = [obs for obs in observations if "--help" in obs.command]
    for obs in help_obs:
        for token in _FORBIDDEN_HELP_TOKENS:
            assert token not in obs.output, (
                f"Forbidden token {token!r} leaked into {obs.command!r} help:\n"
                f"{obs.output}"
            )


def _assert_first_time_help_output(observations: list[_Observation]) -> None:
    top_help = observations[0].output
    for expected_cmd in ("index", "search", "status", "server"):
        assert expected_cmd in top_help, (
            f"Expected command {expected_cmd!r} missing from --help:\n{top_help}"
        )
    index_help = observations[1].output
    assert "docs/indexing.md" in index_help, (
        f"Cross-reference to docs/indexing.md missing from index --help:\n{index_help}"
    )


def _assert_status_output_is_plain(observations: list[_Observation]) -> None:
    status_out = observations[2].output
    assert "Compute:" in status_out
    assert "Index storage:" in status_out
    assert "Source code chunks:" in status_out
    assert "GPU:" not in status_out
    assert "Search data:" not in status_out
    assert "Device:" not in status_out
    assert "Storage:" not in status_out
    assert "Search Concurrency" not in status_out
    for forbidden in ("┌", "└", "│"):
        assert forbidden not in status_out


class TestFirstTimeIndexer:
    """An operator who has just installed the tool and is learning the CLI.

    Scripted sequence:
        vaultspec-rag --help
        vaultspec-rag index --help
        vaultspec-rag status

    Asserts exit 0 on all three and that no developer internals leak
    into the help output.
    """

    pytestmark: typing.ClassVar = [pytest.mark.integration]

    def test_persona(self, tmp_path: Path) -> None:
        observations = _observe_first_time_indexer(tmp_path)
        _assert_observations_succeeded(observations)
        _assert_help_observations_clean(observations)
        _assert_first_time_help_output(observations)
        _assert_status_output_is_plain(observations)


# ---------------------------------------------------------------------------
# Persona 2: Search power user
# ---------------------------------------------------------------------------


class TestSearchPowerUser:
    """A developer who uses the CLI daily to navigate the codebase.

    Scripted sequence (workspace-free help + live GPU search):
        vaultspec-rag search --help   (no GPU; workspace-free)
        vaultspec-rag search "embedding model" --type code --language python
            (live in-process GPU search via ``subprocess_gpu`` marker)

    Asserts help contains the Code/Vault filter panels and search returns
    ranked output.
    """

    pytestmark: typing.ClassVar = [pytest.mark.integration]

    def test_search_help(self) -> None:
        """``search --help`` lists filters plainly and contains no leaked tokens."""
        r = runner.invoke(app, ["search", "--help"])
        obs = _Observation(
            command=["search", "--help"],
            exit_code=r.exit_code,
            output=r.output,
        )

        assert obs.exit_code == 0, (
            f"search --help exited {obs.exit_code}:\n{obs.output}"
        )
        for token in _FORBIDDEN_HELP_TOKENS:
            assert token not in obs.output, (
                f"Forbidden token {token!r} leaked into search --help:\n{obs.output}"
            )
        for option in ("--language", "--path", "--doc-type", "--feature"):
            assert option in obs.output, (
                f"Expected filter option {option!r} in search --help:\n{obs.output}"
            )
        for forbidden in ("─", "│", "┌", "┐", "└", "┘"):
            assert forbidden not in obs.output, (
                f"Box drawing {forbidden!r} leaked into search --help:\n{obs.output}"
            )

    @pytest.mark.subprocess_gpu
    def test_live_code_search(self, tmp_path_factory: TempPathFactory) -> None:
        """Real in-process GPU search returns non-empty ranked output."""
        import subprocess
        import sys

        root: Path = tmp_path_factory.mktemp("testimonial-code-search")

        # Build a minimal synthetic vault so the workspace resolver succeeds
        # and there is at least one source file to find.
        from ..corpus import build_synthetic_vault

        build_synthetic_vault(root, n_docs=6, seed=42)

        # Write a small Python stub so code search has something to index.
        src_dir = root / "src" / "testimonial_probe"
        src_dir.mkdir(parents=True)
        (src_dir / "__init__.py").write_text(
            "# probe module\n"
            "def load_embedding_model(device: str = 'cuda') -> None:\n"
            "    '''Load the dense embedding model onto *device*.'''\n",
            encoding="utf-8",
        )

        from ._helpers import _service_env

        # Index/search in the same isolated service-state environment
        # so an unrelated resident service cannot claim this workspace.
        with _service_env(root):
            index_result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "vaultspec_rag",
                    "--target",
                    str(root),
                    "index",
                    "--type",
                    "code",
                ],
                capture_output=True,
                text=True,
                timeout=300,
                cwd=str(root),
                encoding="utf-8",
                errors="replace",
            )
            assert index_result.returncode == 0, (
                f"index --type code failed:\nstdout: {index_result.stdout}\n"
                f"stderr: {index_result.stderr}"
            )
            search_result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "vaultspec_rag",
                    "--target",
                    str(root),
                    "search",
                    "embedding model",
                    "--type",
                    "code",
                    "--language",
                    "python",
                ],
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(root),
                encoding="utf-8",
                errors="replace",
            )
        obs = _Observation(
            command=[
                "search",
                "embedding model",
                "--type",
                "code",
                "--language",
                "python",
            ],
            exit_code=search_result.returncode,
            output=search_result.stdout,
            friction=search_result.stderr[:300] if search_result.stderr else "",
        )

        assert obs.exit_code == 0, (
            f"search command exited {obs.exit_code}.\n"
            f"stdout:\n{obs.output}\nstderr:\n{obs.friction}"
        )
        # Human search output is a line-oriented ranked result, not a score table.
        output_lower = obs.output.lower()
        assert "rank=1" in output_lower or "load_embedding_model" in obs.output, (
            f"Expected ranked code-search result in output:\n{obs.output}"
        )


# ---------------------------------------------------------------------------
# Persona 3: Service operator
# ---------------------------------------------------------------------------


class TestServiceOperator:
    """An operator who manages the running daemon.

    Sub-tests that only need the CLI layer (no live daemon) use CliRunner.
    Sub-tests that need a running daemon use the ``live_service`` fixture
    and are marked ``subprocess_gpu``.
    """

    pytestmark: typing.ClassVar = [pytest.mark.integration]

    # -- workspace-free: no live daemon required ----------------------------

    def test_server_service_is_invalid(self) -> None:
        """``server service`` must no longer be a valid command path."""
        r = runner.invoke(app, ["server", "service", "--help"])
        # Typer exits 2 for unknown sub-commands.
        assert r.exit_code == 2, (
            f"Expected exit 2 for unknown 'server service', got {r.exit_code}.\n"
            f"output:\n{r.output}"
        )
        assert "no such command" in r.output.lower(), (
            f"Expected 'No such command' error for 'server service':\n{r.output}"
        )

    def test_server_status_no_service(self, tmp_path: Path) -> None:
        """``server status`` exits 3 and reports 'stopped' when no daemon is running."""
        from ._helpers import _service_env

        with _service_env(tmp_path):
            r = runner.invoke(
                app,
                ["server", "status"],
                env={"VAULTSPEC_RAG_STATUS_DIR": str(tmp_path)},
            )
        obs = _Observation(
            command=["server", "status"],
            exit_code=r.exit_code,
            output=r.output,
        )
        assert obs.exit_code == 3, (
            f"Expected exit 3 (stopped), got {obs.exit_code}:\n{obs.output}"
        )
        assert "stopped" in obs.output.lower() or "missing" in obs.output.lower(), (
            f"Expected 'stopped'/'missing' in status output:\n{obs.output}"
        )

    def test_server_logs_no_service(self, tmp_path: Path) -> None:
        """``server logs`` exits 3 with a remediation message when down."""
        from ._helpers import _service_env

        with _service_env(tmp_path):
            r = runner.invoke(
                app,
                ["server", "logs"],
                env={"VAULTSPEC_RAG_STATUS_DIR": str(tmp_path)},
            )
        obs = _Observation(
            command=["server", "logs"],
            exit_code=r.exit_code,
            output=r.output,
        )
        assert obs.exit_code == 3, (
            f"Expected exit 3, got {obs.exit_code}:\n{obs.output}"
        )
        assert obs.output.strip(), "Expected non-empty output (remediation hint)"

    def test_server_jobs_no_service(self, tmp_path: Path) -> None:
        """``server jobs`` exits 3 with a remediation message when down."""
        from ._helpers import _service_env

        with _service_env(tmp_path):
            r = runner.invoke(
                app,
                ["server", "jobs"],
                env={"VAULTSPEC_RAG_STATUS_DIR": str(tmp_path)},
            )
        obs = _Observation(
            command=["server", "jobs"],
            exit_code=r.exit_code,
            output=r.output,
        )
        assert obs.exit_code == 3, (
            f"Expected exit 3, got {obs.exit_code}:\n{obs.output}"
        )
        assert obs.output.strip(), "Expected non-empty output (remediation hint)"

    def test_server_updates_status_no_service(self, tmp_path: Path) -> None:
        """``server updates status`` exits 3 when no daemon is running."""
        from ._helpers import _service_env

        with _service_env(tmp_path):
            r = runner.invoke(
                app,
                ["server", "updates", "status"],
                env={"VAULTSPEC_RAG_STATUS_DIR": str(tmp_path)},
            )
        obs = _Observation(
            command=["server", "updates", "status"],
            exit_code=r.exit_code,
            output=r.output,
        )
        assert obs.exit_code == 3, (
            f"Expected exit 3, got {obs.exit_code}:\n{obs.output}"
        )

    def test_server_projects_list_no_service(self, tmp_path: Path) -> None:
        """``server projects list`` exits 3 when no daemon is running."""
        from ._helpers import _service_env

        with _service_env(tmp_path):
            r = runner.invoke(
                app,
                ["server", "projects", "list"],
                env={"VAULTSPEC_RAG_STATUS_DIR": str(tmp_path)},
            )
        obs = _Observation(
            command=["server", "projects", "list"],
            exit_code=r.exit_code,
            output=r.output,
        )
        assert obs.exit_code == 3, (
            f"Expected exit 3, got {obs.exit_code}:\n{obs.output}"
        )

    # -- live daemon: subprocess_gpu ----------------------------------------

    @pytest.mark.subprocess_gpu
    def test_server_lifecycle_and_observability(
        self, live_service: tuple[int, Path]
    ) -> None:
        """Exercise the flattened lifecycle over a running daemon.

        Uses the ``live_service`` fixture which spawns a real GPU-backed
        daemon on an ephemeral port.  Exercises:
            server status   → exit 0, 'running'
            server logs     → exit 0, non-empty output
            server jobs     → exit 0, non-empty output
            server updates status → exit 0, non-empty output
            server projects list  → exit 0, non-empty output
        """
        port, status_dir = live_service

        observations: list[_Observation] = []
        env = {"VAULTSPEC_RAG_STATUS_DIR": str(status_dir)}

        for cmd in [
            ["server", "status"],
            ["server", "logs"],
            ["server", "jobs"],
            ["server", "updates", "status"],
            ["server", "projects", "list"],
        ]:
            r = runner.invoke(app, cmd, env=env)
            observations.append(
                _Observation(
                    command=cmd,
                    exit_code=r.exit_code,
                    output=r.output,
                    friction=f"exception: {r.exception}" if r.exception else "",
                )
            )

        # All commands must exit 0 against a live daemon.
        for obs in observations:
            assert obs.exit_code == 0, (
                f"Command {obs.command!r} exited {obs.exit_code} against live daemon.\n"
                f"friction: {obs.friction!r}\n"
                f"output:\n{obs.output}"
            )

        # server status must confirm the daemon is running.
        status_obs = next(o for o in observations if o.command == ["server", "status"])
        assert "running" in status_obs.output.lower(), (
            f"Expected 'running' in server status output:\n{status_obs.output}"
        )
        assert str(port) in status_obs.output, (
            f"Expected port {port} in server status output:\n{status_obs.output}"
        )

        # Each remaining observability command must produce non-empty output.
        for obs in observations:
            if obs.command == ["server", "status"]:
                continue
            assert obs.output.strip(), (
                f"Expected non-empty output from {obs.command!r}:\n{obs.output!r}"
            )
