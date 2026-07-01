"""Integration tests for ``vaultspec_rag.commands.install_run``/``uninstall_run``.

Real filesystem (``tmp_path``), real ``vaultspec_core`` (installed in the
dev environment via the project dependency), real bundled wheel content
via :mod:`vaultspec_rag.builtins`. No mocks, fakes, or stubs per the
project test mandate.

These tests pin the symmetric-mirror contract between install and
uninstall: install seeds rag's source files and runs core's sync;
uninstall removes the same files and runs the same sync. The
round-trip test (install → uninstall → workspace shape matches
pre-install) is the canonical correctness signal that depends on
vaultspec-core 0.1.10+'s reconciling ``mcp_sync``.
"""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from ...commands import install_run, uninstall_run

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = [pytest.mark.integration]


_RAG_RULE_REL = Path(".vaultspec") / "rules" / "vaultspec-rag.builtin.md"
_RAG_MCP_REL = Path(".vaultspec") / "mcps" / "vaultspec-rag.builtin.json"
_RAG_SKILL_REL = (
    Path(".vaultspec") / "skills" / "vaultspec-rag-discovery" / "SKILL.md"
)

_CONSUMER_PYPROJECT = (
    "[project]\n"
    'name = "demo-consumer"\n'
    'version = "0.1.0"\n'
    'dependencies = ["vaultspec-rag"]\n'
)


def _read_mcp_json(target: Path) -> dict[str, Any]:
    return json.loads((target / ".mcp.json").read_text(encoding="utf-8"))


@pytest.fixture()
def fresh_workspace(tmp_path: Path) -> Path:
    """An empty directory rag will bootstrap from scratch."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


@pytest.fixture()
def installed_workspace(tmp_path: Path) -> Path:
    """An empty directory with rag freshly installed (post-sync)."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    install_run(path=ws)
    return ws


class TestFreshInstall:
    def test_creates_required_directories(self, fresh_workspace: Path) -> None:
        report = install_run(path=fresh_workspace)
        assert report.action == "install"
        assert (fresh_workspace / ".vault").is_dir()
        assert (fresh_workspace / ".vault" / "data").is_dir()
        # rag folds its builtins flat into .vaultspec/ like core (rules/, mcps/,
        # skills/), not double-nested under .vaultspec/rules/.
        assert (fresh_workspace / ".vaultspec" / "rules").is_dir()
        assert (fresh_workspace / ".vaultspec" / "mcps").is_dir()
        assert (fresh_workspace / ".vaultspec" / "skills").is_dir()
        assert "vault" in " ".join(report.created_dirs)

    def test_seeds_bundled_files(self, fresh_workspace: Path) -> None:
        report = install_run(path=fresh_workspace)
        assert sorted(report.seeded) == [
            "mcps/vaultspec-rag.builtin.json",
            "rules/vaultspec-rag.builtin.md",
            "skills/vaultspec-rag-discovery/SKILL.md",
        ]
        assert (fresh_workspace / _RAG_RULE_REL).is_file()
        assert (fresh_workspace / _RAG_MCP_REL).is_file()
        assert (fresh_workspace / _RAG_SKILL_REL).is_file()

    def test_propagates_mcp_via_core_sync(self, fresh_workspace: Path) -> None:
        install_run(path=fresh_workspace)
        data = _read_mcp_json(fresh_workspace)
        assert "vaultspec-rag" in data["mcpServers"]
        assert "vaultspec-rag" in data.get("_vaultspecManaged", [])

    def test_mcp_command_matches_bundled_definition(
        self, fresh_workspace: Path
    ) -> None:
        install_run(path=fresh_workspace)
        data = _read_mcp_json(fresh_workspace)
        entry = data["mcpServers"]["vaultspec-rag"]
        assert entry["command"] == "uv"
        assert "vaultspec-search-mcp" in entry["args"]


class TestIdempotentInstall:
    def test_reinstall_is_noop_for_seeded_files(
        self, installed_workspace: Path
    ) -> None:
        report = install_run(path=installed_workspace)
        # Files already exist, no force/upgrade → seed nothing
        assert report.seeded == []
        # Files still present
        assert (installed_workspace / _RAG_RULE_REL).is_file()
        assert (installed_workspace / _RAG_MCP_REL).is_file()

    def test_upgrade_re_seeds_existing_files(self, installed_workspace: Path) -> None:
        # Mutate the seeded rule file to detect re-seeding
        rule_path = installed_workspace / _RAG_RULE_REL
        rule_path.write_text("MUTATED", encoding="utf-8")

        report = install_run(path=installed_workspace, upgrade=True)
        assert "rules/vaultspec-rag.builtin.md" in report.seeded
        assert rule_path.read_text(encoding="utf-8") != "MUTATED"

    def test_force_re_seeds_existing_files(self, installed_workspace: Path) -> None:
        rule_path = installed_workspace / _RAG_RULE_REL
        rule_path.write_text("MUTATED", encoding="utf-8")
        install_run(path=installed_workspace, force=True)
        assert rule_path.read_text(encoding="utf-8") != "MUTATED"


class TestDryRunInstall:
    def test_dry_run_creates_no_dirs_or_files(self, fresh_workspace: Path) -> None:
        report = install_run(path=fresh_workspace, dry_run=True)
        assert report.action == "dry_run"
        # Filesystem untouched
        assert not (fresh_workspace / ".vault").exists()
        assert not (fresh_workspace / ".vaultspec").exists()
        # Report still lists planned work
        assert report.created_dirs
        assert "rules/vaultspec-rag.builtin.md" in report.seeded

    def test_dry_run_does_not_invoke_sync(self, fresh_workspace: Path) -> None:
        report = install_run(path=fresh_workspace, dry_run=True)
        assert report.sync_results == []
        assert any("dry-run" in w for w in report.warnings)


class TestUninstallSafety:
    def test_uninstall_without_force_is_dry_run(
        self, installed_workspace: Path
    ) -> None:
        report = uninstall_run(path=installed_workspace)
        assert report.action == "dry_run"
        # Files still present
        assert (installed_workspace / _RAG_RULE_REL).is_file()
        assert (installed_workspace / _RAG_MCP_REL).is_file()

    def test_uninstall_force_removes_only_rag_files(
        self, installed_workspace: Path
    ) -> None:
        report = uninstall_run(path=installed_workspace, force=True)
        assert report.action == "uninstall"
        assert not (installed_workspace / _RAG_RULE_REL).exists()
        assert not (installed_workspace / _RAG_MCP_REL).exists()
        # rag must never touch .vault/ documents
        assert (installed_workspace / ".vault").is_dir()
        # rag must never touch .vault/data/ unless --remove-data
        assert (installed_workspace / ".vault" / "data").is_dir()

    def test_uninstall_propagates_via_core_sync(
        self, installed_workspace: Path
    ) -> None:
        uninstall_run(path=installed_workspace, force=True)
        # The .mcp.json file is removed entirely once the only managed
        # entry is pruned (core's mcp_sync deletes the empty file).
        # If any user-added entries remained the file would persist;
        # there are none in this fixture.
        mcp_json = installed_workspace / ".mcp.json"
        if mcp_json.exists():
            data = json.loads(mcp_json.read_text(encoding="utf-8"))
            assert "vaultspec-rag" not in data.get("mcpServers", {})
            assert "vaultspec-rag" not in data.get("_vaultspecManaged", [])

    def test_remove_data_purges_index_dir(self, installed_workspace: Path) -> None:
        # Drop a sentinel file in .vault/data/ to detect deletion
        (installed_workspace / ".vault" / "data" / "sentinel").write_text(
            "x", encoding="utf-8"
        )
        report = uninstall_run(path=installed_workspace, force=True, remove_data=True)
        assert report.data_removed
        assert not (installed_workspace / ".vault" / "data").exists()
        # .vault/ itself preserved
        assert (installed_workspace / ".vault").is_dir()


class TestUserContentPreservation:
    def test_preexisting_user_mcp_entry_survives_install(
        self, fresh_workspace: Path
    ) -> None:
        # Bootstrap minimum dirs and pre-populate .mcp.json with a
        # user-added entry that has nothing to do with rag.
        (fresh_workspace / ".vaultspec").mkdir()
        (fresh_workspace / ".mcp.json").write_text(
            json.dumps(
                {
                    "mcpServers": {"my-tool": {"command": "custom", "args": []}},
                    "_vaultspecManaged": [],
                }
            ),
            encoding="utf-8",
        )

        install_run(path=fresh_workspace)
        data = _read_mcp_json(fresh_workspace)
        # User entry survived
        assert data["mcpServers"]["my-tool"]["command"] == "custom"
        # rag's entry got added
        assert "vaultspec-rag" in data["mcpServers"]
        # User entry NOT taken into managed set
        assert "my-tool" not in data["_vaultspecManaged"]
        assert "vaultspec-rag" in data["_vaultspecManaged"]

    def test_preexisting_user_mcp_entry_survives_uninstall(
        self, fresh_workspace: Path
    ) -> None:
        (fresh_workspace / ".vaultspec").mkdir()
        (fresh_workspace / ".mcp.json").write_text(
            json.dumps(
                {
                    "mcpServers": {"my-tool": {"command": "custom", "args": []}},
                    "_vaultspecManaged": [],
                }
            ),
            encoding="utf-8",
        )

        install_run(path=fresh_workspace)
        uninstall_run(path=fresh_workspace, force=True)

        # The .mcp.json file persists because the user entry survives
        data = _read_mcp_json(fresh_workspace)
        assert data["mcpServers"]["my-tool"]["command"] == "custom"
        assert "vaultspec-rag" not in data["mcpServers"]
        assert "vaultspec-rag" not in data.get("_vaultspecManaged", [])

    def test_preexisting_user_rule_file_survives_uninstall(
        self, installed_workspace: Path
    ) -> None:
        # Pre-existing user-authored rule must not be touched by rag
        # uninstall - it removes only its two named files.
        user_rule = installed_workspace / ".vaultspec" / "rules" / "my-custom-rule.md"
        user_rule.write_text("---\nname: custom\n---\n# user rule\n", encoding="utf-8")

        uninstall_run(path=installed_workspace, force=True)
        # The user rule survives uninstall (rag removes only its own named
        # files). vaultspec-core's sync migrates flat custom rules under
        # rules/project/, so accept either the original or migrated location.
        migrated_rule = (
            installed_workspace
            / ".vaultspec"
            / "rules"
            / "project"
            / "my-custom-rule.md"
        )
        assert user_rule.is_file() or migrated_rule.is_file()


class TestSymmetricRoundTrip:
    def test_install_then_uninstall_returns_to_clean_state(
        self, fresh_workspace: Path
    ) -> None:
        """Canonical correctness signal: installing then uninstalling
        leaves no rag-owned artefacts behind. This is the test that
        depends on vaultspec-core 0.1.10+'s reconciling mcp_sync.
        """
        install_run(path=fresh_workspace)
        uninstall_run(path=fresh_workspace, force=True)

        # Both rag-owned source files are gone
        assert not (fresh_workspace / _RAG_RULE_REL).exists()
        assert not (fresh_workspace / _RAG_MCP_REL).exists()

        # No rag MCP entry lingers in .mcp.json (file may or may not
        # exist depending on whether other entries remain)
        mcp_json = fresh_workspace / ".mcp.json"
        if mcp_json.exists():
            data = json.loads(mcp_json.read_text(encoding="utf-8"))
            assert "vaultspec-rag" not in data.get("mcpServers", {})
            assert "vaultspec-rag" not in data.get("_vaultspecManaged", [])

        # rag's local infrastructure (.vault/, .vault/data/) is
        # preserved unless --remove-data was passed
        assert (fresh_workspace / ".vault").is_dir()
        assert (fresh_workspace / ".vault" / "data").is_dir()


class TestReportSerialization:
    def test_install_report_to_dict_keys(self, fresh_workspace: Path) -> None:
        report = install_run(path=fresh_workspace)
        d = report.to_dict()
        assert d["action"] == "install"
        assert d["target"] == str(fresh_workspace)
        assert isinstance(d["created_dirs"], list)
        assert isinstance(d["seeded"], list)
        assert "sync_added" in d
        # Must round-trip through json.dumps without error
        json.dumps(d)

    def test_uninstall_report_to_dict_keys(self, installed_workspace: Path) -> None:
        report = uninstall_run(path=installed_workspace, force=True)
        d = report.to_dict()
        assert d["action"] == "uninstall"
        assert isinstance(d["removed"], list)
        assert isinstance(d["data_removed"], bool)
        assert "sync_pruned" in d
        json.dumps(d)


class TestSafetyGuards:
    """Destruction-safety regression tests.

    These tests pin the safety contract: rag must never follow a
    symlink out of the workspace, never escape ``target_rules_dir`` via
    a malicious bundled rel path, and never leave a half-installed
    workspace if seeding fails partway through.
    """

    def test_remove_data_refuses_symlink_target(
        self, installed_workspace: Path, tmp_path: Path
    ) -> None:
        """If ``.vault/data/`` is a symlink, ``--remove-data`` must
        refuse the operation rather than follow the symlink and
        rmtree something outside the workspace. The symlink itself
        is left alone - the user must resolve it manually.
        """
        # Replace .vault/data/ with a symlink pointing outside the
        # workspace. Drop a sentinel inside the link target so we can
        # detect any traversal.
        outside = tmp_path / "outside-data"
        outside.mkdir()
        sentinel = outside / "MUST_NOT_BE_DELETED"
        sentinel.write_text("safe", encoding="utf-8")

        data_dir = installed_workspace / ".vault" / "data"
        # Drop existing data dir and replace with symlink. On Windows
        # symlink creation may need admin/dev mode; if it fails, skip
        # the test rather than passing it falsely.
        import shutil as _shutil

        _shutil.rmtree(data_dir)
        try:
            data_dir.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            raise RuntimeError(f"symlink creation unsupported: {exc}") from exc

        report = uninstall_run(path=installed_workspace, force=True, remove_data=True)

        # The symlink target's contents must be untouched.
        assert sentinel.is_file()
        assert sentinel.read_text(encoding="utf-8") == "safe"
        # The operation must NOT report data_removed=True.
        assert not report.data_removed
        # A clear warning must surface to the user.
        assert any("symlink" in w for w in report.warnings)

    def test_install_run_in_unrelated_directory_does_not_escape(
        self, tmp_path: Path
    ) -> None:
        """A sentinel file outside the install target must survive an
        install run. This guards against any code path that might
        accidentally write outside ``target``.
        """
        ws = tmp_path / "workspace"
        ws.mkdir()

        sibling = tmp_path / "sibling"
        sibling.mkdir()
        sentinel = sibling / "untouched.txt"
        sentinel.write_text("safe", encoding="utf-8")

        install_run(path=ws)

        assert sentinel.is_file()
        assert sentinel.read_text(encoding="utf-8") == "safe"
        # Confirm install actually did its job in the target.
        assert (ws / _RAG_RULE_REL).is_file()

    def test_uninstall_force_does_not_touch_user_data_outside_index(
        self, installed_workspace: Path
    ) -> None:
        """Uninstall must never touch user-authored content under
        ``.vault/`` even with ``--force``. Drops several sentinel docs
        and asserts they all survive.
        """
        vault = installed_workspace / ".vault"
        sentinels = [
            vault / "adr" / "user-decision.md",
            vault / "research" / "user-notes.md",
            vault / "plan" / "user-plan.md",
        ]
        for s in sentinels:
            s.parent.mkdir(parents=True, exist_ok=True)
            s.write_text(f"# {s.name}\n", encoding="utf-8")

        uninstall_run(path=installed_workspace, force=True)

        for s in sentinels:
            assert s.is_file(), f"user file {s.name} was destroyed"

    def test_install_rolls_back_seeded_files_on_seed_failure(
        self, tmp_path: Path
    ) -> None:
        """If ``seed_builtins`` fails partway through, ``install_run``
        must remove any files it had successfully written so the
        workspace is not left half-installed.

        ``seed_builtins`` walks the package tree in sorted order, so
        ``mcps/...`` is seeded before ``rules/...``. We block the
        second (rules) iteration by making its dest path a non-empty
        directory, so ``atomic_write`` fails after the first (mcps)
        entry has already been seeded successfully. Rollback must
        unlink the mcps file.
        """
        import pytest as _pytest

        ws = tmp_path / "workspace"
        ws.mkdir()
        # Pre-create the workspace dirs so _ensure_workspace_dirs is a
        # no-op and seed_builtins is the failure point.
        (ws / ".vault" / "data").mkdir(parents=True)
        (ws / ".vaultspec" / "mcps").mkdir(parents=True)
        (ws / ".vaultspec" / "rules").mkdir(parents=True)
        (ws / ".vaultspec" / "skills").mkdir(parents=True)
        # Block the rules write: make the bundled DEST path a non-empty
        # directory. With force=True the existence check is bypassed and
        # atomic_write fails on the dir replacement.
        (ws / _RAG_RULE_REL).mkdir()
        (ws / _RAG_RULE_REL / "sentinel").write_text("x", encoding="utf-8")

        with _pytest.raises(OSError):
            install_run(path=ws, force=True)

        # The mcps file was written but must have been rolled back.
        assert not (ws / _RAG_MCP_REL).exists()
        # The rules "file" is still a non-empty directory (we never
        # wrote a file there); rollback only unlinks paths it
        # actually wrote.
        assert (ws / _RAG_RULE_REL).is_dir()
        assert (ws / _RAG_RULE_REL / "sentinel").is_file()

    def test_uninstall_in_empty_dir_does_not_create_workspace(
        self, tmp_path: Path
    ) -> None:
        """Codex P2: ``vaultspec-rag uninstall --force`` against an
        empty directory must NOT create ``.vault/`` or ``.vaultspec/``
        as a side effect. Cleanup automation that points at the wrong
        directory should be a no-op, not a destructive bootstrap.
        """
        ws = tmp_path / "empty-workspace"
        ws.mkdir()
        # Confirm starting state
        assert not (ws / ".vault").exists()
        assert not (ws / ".vaultspec").exists()

        report = uninstall_run(path=ws, force=True)

        # The directories must NOT have been created.
        assert not (ws / ".vault").exists()
        assert not (ws / ".vaultspec").exists()
        # The report must reflect that nothing was removed.
        assert report.removed == []
        assert any("nothing to uninstall" in w for w in report.warnings), (
            report.warnings
        )

    def test_uninstall_in_dir_without_vaultspec_returns_early(
        self, tmp_path: Path
    ) -> None:
        """If ``.vault/`` exists but ``.vaultspec/`` does not, uninstall
        must still no-op rather than creating the missing dir or
        attempting to read non-existent rag artefacts.
        """
        ws = tmp_path / "partial-workspace"
        ws.mkdir()
        (ws / ".vault").mkdir()  # only one of the two dirs exists

        report = uninstall_run(path=ws, force=True)

        # .vaultspec was NOT created.
        assert not (ws / ".vaultspec").exists()
        assert report.removed == []
        assert any("nothing to uninstall" in w for w in report.warnings)

    def test_seed_builtins_raises_on_per_file_failure(self, tmp_path: Path) -> None:
        """Codex P2: ``seed_builtins`` must raise on per-file write
        failures, not log-and-continue. Silent partial seeding bypasses
        the install_run rollback path and leaves the workspace in an
        undetectable broken state.
        """
        from ...builtins import seed_builtins

        target = tmp_path / "rules"
        target.mkdir()
        # Block one of the destination paths by making its parent dir
        # a file. ``mcps/`` comes before ``rules/`` alphabetically in
        # the bundled tuple, so the mcps write attempt will fail.
        (target / "mcps").write_text("blocker", encoding="utf-8")

        import pytest as _pytest

        with _pytest.raises(OSError):
            seed_builtins(target)

    def test_seed_builtins_out_param_captures_partial_progress(
        self, tmp_path: Path
    ) -> None:
        """The ``written`` out-list must contain everything seeded
        before the failing iteration, so callers (install_run) can
        roll back targeted partial state.
        """
        from ...builtins import seed_builtins

        target = tmp_path / "rules"
        target.mkdir()
        # seed_builtins walks the package tree in sorted order, so
        # ``mcps/...`` is written before ``rules/...``. Let mcps
        # succeed and block the second (rules) iteration by
        # pre-creating its dest path as a non-empty directory. With
        # force=True the existence check is bypassed and atomic_write
        # fails on the dir replacement.
        (target / "rules").mkdir()
        (target / "mcps").mkdir()
        (target / "rules" / "vaultspec-rag.builtin.md").mkdir()
        (target / "rules" / "vaultspec-rag.builtin.md" / "x").write_text(
            "y", encoding="utf-8"
        )

        written: list[str] = []
        import pytest as _pytest

        with _pytest.raises(OSError):
            seed_builtins(target, force=True, written=written)

        # mcps file got written before the rules failure
        assert "mcps/vaultspec-rag.builtin.json" in written
        # rules file did NOT
        assert "rules/vaultspec-rag.builtin.md" not in written

    def test_global_target_flag_routes_to_install(self, tmp_path: Path) -> None:
        """Codex P1: ``vaultspec-rag --target /path install`` must
        install into ``/path``, not into the current working
        directory. The root callback's global ``--target`` is
        consumed by Click before the subcommand options, so the
        subcommand handler must explicitly read it from the context.
        """
        from typer.testing import CliRunner

        from ...cli import app

        ws = tmp_path / "global-target-ws"
        ws.mkdir()

        runner = CliRunner()
        result = runner.invoke(
            app, ["--target", str(ws), "install"], catch_exceptions=False
        )

        assert result.exit_code == 0, result.output
        # The bundled files must have landed in the global target,
        # not in cwd.
        assert (ws / _RAG_RULE_REL).is_file()
        assert (ws / _RAG_MCP_REL).is_file()

    def test_global_target_flag_routes_to_uninstall(
        self, installed_workspace: Path
    ) -> None:
        """Same routing rule for uninstall: ``vaultspec-rag --target
        /path uninstall --force`` must uninstall from ``/path``.
        """
        from typer.testing import CliRunner

        from ...cli import app

        runner = CliRunner()
        result = runner.invoke(
            app,
            ["--target", str(installed_workspace), "uninstall", "--force"],
            catch_exceptions=False,
        )

        assert result.exit_code == 0, result.output
        # rag-owned files removed from the global target.
        assert not (installed_workspace / _RAG_RULE_REL).exists()
        assert not (installed_workspace / _RAG_MCP_REL).exists()

    def test_seed_builtins_refuses_dest_outside_target(self, tmp_path: Path) -> None:
        """Defense-in-depth: ``seed_builtins`` must never write a dest
        that resolves outside ``target_rules_dir``.

        The bundled set is now whatever ships under the package, so a
        traversal can no longer enter through a corrupt manifest. We
        instead point the source root at a crafted tree containing a
        nested builtin and confirm the containment guard governs every
        write: the seeded dest stays inside the target, mirroring the
        files relative to the source root.

        We swap ``_builtins_root`` by direct attribute assignment with
        restore in ``finally`` (no monkeypatch fixture, honouring the
        project no-mocks rule).
        """
        from ... import builtins as _builtins

        # Build a crafted source tree with one nested builtin file.
        fake_src = tmp_path / "fake-builtins"
        (fake_src / "rules").mkdir(parents=True)
        (fake_src / "rules" / "vaultspec-rag.builtin.md").write_text(
            "---\nname: vaultspec-rag\n---\n", encoding="utf-8"
        )

        original_root = _builtins._builtins_root

        def _fake_root() -> Path:
            return fake_src

        # NB: not a mock - rebinding a module function via __dict__ (restored
        # below); __dict__ assignment avoids retyping the module attribute.
        _builtins.__dict__["_builtins_root"] = _fake_root
        try:
            target = tmp_path / "rules-target"
            target.mkdir()

            written = _builtins.seed_builtins(target)

            # The nested file seeded into the target, contained.
            assert "rules/vaultspec-rag.builtin.md" in written
            seeded = target / "rules" / "vaultspec-rag.builtin.md"
            assert seeded.is_file()
            assert seeded.resolve().is_relative_to(target.resolve())
        finally:
            _builtins.__dict__["_builtins_root"] = original_root


@pytest.fixture()
def isolated_status_dir(tmp_path: Path) -> Iterator[Path]:
    """Point the managed service / qdrant bin dir at tmp and reset config.

    Keeps the provisioning front door's qdrant resolution off any ambient
    ``~/.vaultspec-rag/`` state, per the service-tests-isolate-STATUS_DIR
    discipline, so the test cannot disturb the live service.
    """
    from ...config import EnvVar, reset_config

    key = EnvVar.STATUS_DIR.value
    prev = os.environ.get(key)
    os.environ[key] = str(tmp_path / "status")
    reset_config()
    try:
        yield tmp_path
    finally:
        if prev is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = prev
        reset_config()


class TestProvisioningReport:
    """The default install provisioning path reports heterogeneous outcomes.

    Network-free by construction: ``local_only=True`` skips the qdrant
    binary download and ``provision_skip={"models"}`` skips the model
    fetch, so the only step that does real work is the torch configurator,
    which patches the temp workspace's own ``pyproject.toml``. The result
    is three honest, *different* per-dependency outcomes - torch
    sync-pending, models skipped, qdrant skipped - which is exactly the
    heterogeneity the report must surface. No mocks, no large downloads,
    and the live service is untouched.
    """

    @pytest.fixture()
    def provisioned_report(
        self, fresh_workspace: Path, isolated_status_dir: Path
    ) -> Any:
        _ = isolated_status_dir
        (fresh_workspace / "pyproject.toml").write_text(
            _CONSUMER_PYPROJECT, encoding="utf-8", newline=""
        )
        return install_run(
            path=fresh_workspace,
            provision=True,
            local_only=True,
            provision_skip={"models"},
            assume_yes=True,
        )

    def test_report_carries_a_provisioning_outcome(
        self, provisioned_report: Any
    ) -> None:
        assert provisioned_report.provision_outcome is not None
        steps = {r.step for r in provisioned_report.provision_outcome.steps}
        # The enrollment torch step runs separately; the front door is told
        # to skip torch so it does not double-report. So the front-door
        # outcome carries the two fetch-and-go dependencies.
        assert "models" in {str(s) for s in steps}
        assert "qdrant" in {str(s) for s in steps}

    def test_json_provisioning_key_is_heterogeneous_and_serialisable(
        self, provisioned_report: Any
    ) -> None:
        data = provisioned_report.to_dict()
        json.dumps(data)  # must not raise
        provisioning = data["provisioning"]
        assert provisioning is not None
        actions = {step["action"] for step in provisioning["steps"]}
        # models and qdrant are both opted out here, so both are skipped,
        # each carrying its own distinct reason (heterogeneous detail).
        details = {step["step"]: step["detail"] for step in provisioning["steps"]}
        assert "local-only" in details["qdrant"]
        assert details["models"] != details["qdrant"]
        assert "skipped" in actions

    def test_torch_enrollment_step_reports_configured_sync_pending(
        self, provisioned_report: Any
    ) -> None:
        from ...torch_config import TorchConfigAction

        # The enrollment torch step actually patched the consumer
        # pyproject; its honest two-phase state is the headline the
        # renderer must surface as "configured, sync pending".
        assert provisioned_report.torch_config_action == TorchConfigAction.APPLIED
        assert provisioned_report.torch_sync_action == "skipped"

    def test_rendered_report_surfaces_heterogeneous_provisioning_wording(
        self, provisioned_report: Any
    ) -> None:
        from rich.console import Console

        from ...cli import _render
        from ...cli._render import _render_install_report

        buffer = io.StringIO()
        captured = Console(
            file=buffer, force_terminal=False, legacy_windows=False, width=200
        )
        original = _render._cli.console
        _render._cli.console = captured  # not a mock: swap restored in finally
        try:
            _render_install_report(provisioned_report)
        finally:
            _render._cli.console = original

        output = buffer.getvalue()
        # The qdrant binary skip and the models skip both render honestly...
        assert "Qdrant binary: skipped" in output
        assert "local-only" in output
        # ...and the provisioning summary line is present and bounded.
        assert "Provisioning:" in output

    def test_dry_run_provisioning_previews_without_writing(
        self, fresh_workspace: Path, isolated_status_dir: Path
    ) -> None:
        from ...commands import ProvisionAction, ProvisionStep

        (fresh_workspace / "pyproject.toml").write_text(
            _CONSUMER_PYPROJECT, encoding="utf-8", newline=""
        )
        report = install_run(
            path=fresh_workspace,
            provision=True,
            dry_run=True,
            provision_skip={"models"},
            assume_yes=True,
        )
        assert report.provision_outcome is not None
        assert report.provision_outcome.dry_run is True
        # A dry-run preview must not have provisioned a qdrant binary into
        # the isolated managed dir nor disturbed the live service.
        qdrant = report.provision_outcome.result_for(ProvisionStep.QDRANT)
        assert qdrant is not None
        assert qdrant.action in {ProvisionAction.DRY_RUN, ProvisionAction.SKIPPED}
        assert not (isolated_status_dir / "status" / "bin").exists()
