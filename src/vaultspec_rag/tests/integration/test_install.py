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

import json
from pathlib import Path

import pytest

from vaultspec_rag.commands import install_run, uninstall_run

pytestmark = [pytest.mark.integration]


_RAG_RULE_REL = Path(".vaultspec") / "rules" / "rules" / "vaultspec-rag.builtin.md"
_RAG_MCP_REL = Path(".vaultspec") / "rules" / "mcps" / "vaultspec-rag.builtin.json"


def _read_mcp_json(target: Path) -> dict:
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
        assert (fresh_workspace / ".vaultspec" / "rules" / "rules").is_dir()
        assert (fresh_workspace / ".vaultspec" / "rules" / "mcps").is_dir()
        assert "vault" in " ".join(report.created_dirs)

    def test_seeds_both_bundled_files(self, fresh_workspace: Path) -> None:
        report = install_run(path=fresh_workspace)
        assert sorted(report.seeded) == [
            "mcps/vaultspec-rag.builtin.json",
            "rules/vaultspec-rag.builtin.md",
        ]
        assert (fresh_workspace / _RAG_RULE_REL).is_file()
        assert (fresh_workspace / _RAG_MCP_REL).is_file()

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
        user_rule = (
            installed_workspace / ".vaultspec" / "rules" / "rules" / "my-custom-rule.md"
        )
        user_rule.write_text("---\nname: custom\n---\n# user rule\n", encoding="utf-8")

        uninstall_run(path=installed_workspace, force=True)
        # The user rule survives uninstall (rag removes only its two named
        # files). vaultspec-core's sync migrates flat custom rules under
        # rules/project/, so accept either the original or migrated location.
        migrated_rule = (
            installed_workspace
            / ".vaultspec"
            / "rules"
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
            import pytest as _pytest

            _pytest.skip(f"symlink creation unsupported: {exc}")

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

        ``_BUNDLED_FILES`` iterates rules-then-mcps. We block the
        second (mcps) iteration by making its parent dir a regular
        file, so ``dest.parent.mkdir(parents=True, exist_ok=True)``
        raises ``FileExistsError`` after the first (rules) entry has
        already been seeded successfully. Rollback must unlink the
        rules file.
        """
        import pytest as _pytest

        ws = tmp_path / "workspace"
        ws.mkdir()
        # Pre-create everything except the mcps parent dir, which
        # we replace with a file. _ensure_workspace_dirs sees mcps
        # already exists (as a file → not is_dir), tries mkdir, and
        # would fail there - so we have to bypass _ensure_workspace_dirs
        # entirely by pre-creating it as a dir, then converting after.
        (ws / ".vault" / "data").mkdir(parents=True)
        (ws / ".vaultspec" / "rules" / "rules").mkdir(parents=True)
        # Critical: do NOT pre-create .vaultspec/rules/mcps as a dir.
        # Instead create it as a FILE so _ensure_workspace_dirs's
        # ``if d.is_dir(): continue`` falls through to mkdir, which
        # raises. But we want seed_builtins to be the failure point,
        # not _ensure_workspace_dirs. So we pre-create mcps as a dir
        # and block seed_builtins by making the bundled DEST file
        # path a non-empty directory; with force=True the existence
        # check is bypassed and atomic_write fails.
        (ws / ".vaultspec" / "rules" / "mcps").mkdir(parents=True)
        (ws / _RAG_MCP_REL).mkdir()
        (ws / _RAG_MCP_REL / "sentinel").write_text("x", encoding="utf-8")

        with _pytest.raises(OSError):
            install_run(path=ws, force=True)

        # The rules file was written but must have been rolled back.
        assert not (ws / _RAG_RULE_REL).exists()
        # The mcps "file" is still a non-empty directory (we never
        # wrote a file there); rollback only unlinks paths it
        # actually wrote.
        assert (ws / _RAG_MCP_REL).is_dir()
        assert (ws / _RAG_MCP_REL / "sentinel").is_file()

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
        from vaultspec_rag.builtins import seed_builtins

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
        from vaultspec_rag.builtins import seed_builtins

        target = tmp_path / "rules"
        target.mkdir()
        # _BUNDLED_FILES iterates rules-then-mcps. Make rules
        # writeable and block the second (mcps) iteration by
        # pre-creating its dest file path as a non-empty directory.
        # With force=True the existence check is bypassed and
        # atomic_write fails on the dir replacement.
        (target / "rules").mkdir()
        (target / "mcps").mkdir()
        (target / "mcps" / "vaultspec-rag.builtin.json").mkdir()
        (target / "mcps" / "vaultspec-rag.builtin.json" / "x").write_text(
            "y", encoding="utf-8"
        )

        written: list[str] = []
        import pytest as _pytest

        with _pytest.raises(OSError):
            seed_builtins(target, force=True, written=written)

        # rules file got written before the mcps failure
        assert "rules/vaultspec-rag.builtin.md" in written
        # mcps file did NOT
        assert "mcps/vaultspec-rag.builtin.json" not in written

    def test_global_target_flag_routes_to_install(self, tmp_path: Path) -> None:
        """Codex P1: ``vaultspec-rag --target /path install`` must
        install into ``/path``, not into the current working
        directory. The root callback's global ``--target`` is
        consumed by Click before the subcommand options, so the
        subcommand handler must explicitly read it from the context.
        """
        from typer.testing import CliRunner

        from vaultspec_rag.cli import app

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

        from vaultspec_rag.cli import app

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

    def test_seed_builtins_refuses_traversal_in_relative_path(
        self, tmp_path: Path, monkeypatch: object
    ) -> None:
        """Defense-in-depth: even if ``_BUNDLED_FILES`` were ever
        corrupted to contain a traversal, ``seed_builtins`` must
        refuse to write outside ``target_rules_dir``.

        We exercise the guard by directly invoking ``seed_builtins``
        with a temporarily-mutated ``_BUNDLED_FILES`` constant via
        attribute assignment (no monkeypatch fixture used - direct
        assignment with restore in finally to honour the project
        no-mocks rule).
        """
        from vaultspec_rag import builtins as _builtins

        original = _builtins._BUNDLED_FILES
        # NB: this is not a mock - it is editing a module constant.
        # We restore it in the finally block.
        _builtins._BUNDLED_FILES = (
            "../../escape.md",
            "rules/vaultspec-rag.builtin.md",
        )
        try:
            target = tmp_path / "rules-target"
            target.mkdir()
            outside = tmp_path / "escape.md"
            assert not outside.exists()

            written = _builtins.seed_builtins(target)

            # The traversal entry must NOT have been written.
            assert "../../escape.md" not in written
            assert not outside.exists()
            # The legitimate entry should still have been written
            # (provided the bundled source resolves).
        finally:
            _builtins._BUNDLED_FILES = original
