"""Real installation integration behavior: safety guards."""

from __future__ import annotations

from pathlib import Path  # noqa: TC003

import pytest

from ...commands._install import install_run
from ...commands._uninstall import uninstall_run
from ._install_helpers import (
    _RAG_MCP_REL,
    _RAG_RULE_REL,
    _RAG_SKILL_REL,
    _install,
    workspace_inventory,
)

pytestmark = [pytest.mark.integration]


class TestSafetyGuards:
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

        _install(ws)

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

        ``seed_builtins`` walks the package tree in sorted order. A directory
        at the final skill destination makes Core's real atomic replacement
        fail only after the MCP and rule files were written.
        """
        ws = tmp_path / "workspace"
        ws.mkdir()
        (ws / ".vault" / "data").mkdir(parents=True)
        (ws / ".vaultspec" / "mcps").mkdir(parents=True)
        (ws / ".vaultspec" / "rules").mkdir(parents=True)
        (ws / ".vaultspec" / "skills").mkdir(parents=True)
        skill = ws / _RAG_SKILL_REL
        skill.parent.mkdir(parents=True)
        skill.mkdir()
        (skill / "operator.md").write_bytes(b"preserve\x00")
        before = workspace_inventory(ws)

        report = install_run(path=ws, force=True)

        assert report.mcp_sync_failed
        assert report.mcp_extra_action == "error"
        assert workspace_inventory(ws) == before

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
        restoration in ``finally`` so this test owns the complete lifecycle.
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

            results = _builtins.seed_builtins(target)

            # The nested file seeded into the target, contained.
            assert ("rules/vaultspec-rag.builtin.md", "[ADD]") in results
            seeded = target / "rules" / "vaultspec-rag.builtin.md"
            assert seeded.is_file()
            assert seeded.resolve().is_relative_to(target.resolve())
        finally:
            _builtins.__dict__["_builtins_root"] = original_root
