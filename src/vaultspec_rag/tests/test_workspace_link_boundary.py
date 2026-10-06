"""Install and uninstall stay inside the selected root when a directory is a link.

Real filesystem (``tmp_path``), real links, the real install and uninstall
entry points. No mocks. Every test aims a workspace directory at an
``outside`` tree and asserts that tree comes back byte-for-byte: a write, an
unlink or a recursive delete that followed the link would show there.

The guard tests record the mutation that makes them fail. The shared one,
called "the link check disabled" below, is ``_is_plain`` in
``_plain_directory`` accepting every node, so a link is never refused as one.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Unpack

import pytest
from typer.testing import CliRunner

from .._plain_directory import LinkedDirectoryError
from ..builtins import list_builtins, seed_builtins
from ..cli import app
from ..commands._install import _InstallRunOptions, install_run
from ..commands._models import InstallReport, UninstallReport
from ..commands._uninstall import (
    _remove_candidates,
    _remove_data_dir,
    _remove_obsolete_sentinels,
    uninstall_run,
)
from ..commands._workspace import _resolve_target
from ._directory_links import LINK_KINDS, link_directory, tree_bytes

pytestmark = [pytest.mark.unit]

_VAULT = Path(".vault")
_WORKSPACE = Path(".vaultspec")
_SKIPS: tuple[frozenset[str], ...] = (frozenset(), frozenset({"mcp"}))


def _install(target: Path, **overrides: Unpack[_InstallRunOptions]) -> InstallReport:
    """Run a network-free install that touches nothing but the workspace."""
    options: _InstallRunOptions = {
        "install_mcp": True,
        "configure_torch": False,
        "provision": False,
        "repair_tool_torch": False,
    }
    options.update(overrides)
    return install_run(path=target, **options)


def _relink(container: Path, destination: Path, kind: str) -> None:
    """Move *container* to *destination* and leave a link to it behind."""
    if container.exists():
        container.replace(destination)
    else:
        destination.mkdir()
    link_directory(container, destination, kind)


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    directory = tmp_path / "workspace"
    directory.mkdir()
    return directory


@pytest.fixture()
def outside(tmp_path: Path) -> Path:
    return tmp_path / "outside"


class TestInstallRefusesLinkedContainers:
    @pytest.mark.parametrize("kind", LINK_KINDS)
    @pytest.mark.parametrize("skip", _SKIPS, ids=["full", "skip-mcp"])
    @pytest.mark.parametrize("container", [_VAULT, _WORKSPACE], ids=str)
    def test_a_fresh_install_refuses_a_linked_container_before_creating_anything(
        self,
        workspace: Path,
        outside: Path,
        container: Path,
        skip: frozenset[str],
        kind: str,
    ) -> None:
        """Proven able to fail: without the workspace check on the skipped-MCP
        path of ``_install_run``, the ``.vaultspec`` + ``skip-mcp`` case
        bootstraps ``.vault`` before the bootstrap itself refuses the link, and
        fails on the listing assertion. With the link check disabled the
        refusal is lost, and every case fails on its refusal assertion:
        ``mcp_sync_failed`` for the preflight case, the ``pytest.raises`` for
        the rest.
        """
        _relink(workspace / container, outside, kind)
        (outside / "operator.txt").write_text("operator", encoding="utf-8")
        listing = sorted(os.listdir(workspace))
        before = tree_bytes(outside)

        if container == _WORKSPACE and not skip:
            # The required-node preflight sees this link first and reports it
            # on the install report rather than raising.
            report = _install(workspace, skip=set(skip))
            assert report.mcp_sync_failed
            assert any("unsafe directory topology" in e for e in report.mcp_errors)
        else:
            with pytest.raises(LinkedDirectoryError, match=re.escape(container.name)):
                _install(workspace, skip=set(skip))

        assert sorted(os.listdir(workspace)) == listing
        assert tree_bytes(outside) == before

    @pytest.mark.parametrize("kind", LINK_KINDS)
    @pytest.mark.parametrize("skip", _SKIPS, ids=["full", "skip-mcp"])
    @pytest.mark.parametrize(
        "container", [_WORKSPACE / "rules", _WORKSPACE / "skills"], ids=str
    )
    def test_an_upgrade_refuses_a_linked_directory_beneath_the_workspace(
        self,
        workspace: Path,
        outside: Path,
        container: Path,
        skip: frozenset[str],
        kind: str,
    ) -> None:
        """Neither directory is a required MCP node, so only the workspace
        check stands between the link and a forced re-seed through it.

        Proven able to fail: without the workspace check on the full path of
        ``_install_run``, the ``full`` cases run the placement transaction,
        hit the seed's own refusal and roll back into a failure report, and
        fail on ``DID NOT RAISE``.
        """
        _install(workspace)
        _relink(workspace / container, outside, kind)
        before = tree_bytes(outside)
        inside = tree_bytes(workspace)

        with pytest.raises(LinkedDirectoryError, match=re.escape(container.name)):
            _install(workspace, upgrade=True, force=True, skip=set(skip))

        assert tree_bytes(outside) == before
        assert tree_bytes(workspace) == inside

    @pytest.mark.parametrize("skip", _SKIPS, ids=["full", "skip-mcp"])
    def test_a_preview_refuses_what_a_real_run_refuses(
        self, workspace: Path, outside: Path, skip: frozenset[str]
    ) -> None:
        _relink(workspace / _VAULT, outside, "symlink")

        with pytest.raises(LinkedDirectoryError, match=re.escape(".vault")):
            _install(workspace, dry_run=True, skip=set(skip))

        assert tree_bytes(outside) == {}

    def test_the_cli_reports_the_refusal_as_one_failed_envelope(
        self, workspace: Path, outside: Path
    ) -> None:
        _relink(workspace / _VAULT, outside, "symlink")

        result = CliRunner().invoke(
            app,
            [
                "install",
                "--target",
                str(workspace),
                "--skip",
                "mcp",
                "--no-provision",
                "--no-torch-config",
                "--no-tool-repair",
                "--json",
            ],
        )

        assert result.exit_code == 1, result.output
        envelope = json.loads(result.output)
        assert "unsafe directory topology" in json.dumps(envelope)
        assert tree_bytes(outside) == {}


class TestUninstallRefusesLinkedContainers:
    @pytest.mark.parametrize("kind", LINK_KINDS)
    @pytest.mark.parametrize("skip", _SKIPS, ids=["full", "skip-mcp"])
    @pytest.mark.parametrize(
        "container",
        [_VAULT, _WORKSPACE, _WORKSPACE / "rules", _WORKSPACE / "skills"],
        ids=str,
    )
    def test_uninstall_refuses_a_linked_container_before_removing_anything(
        self,
        workspace: Path,
        outside: Path,
        container: Path,
        skip: frozenset[str],
        kind: str,
    ) -> None:
        """Proven able to fail: without the workspace check in
        ``_uninstall_run``, the run reaches its first removals before a later
        step refuses the link, and fails on the workspace assertion. With the
        link check disabled the refusal is lost, and every case fails on its
        refusal assertion: ``mcp_sync_failed`` for the preflight case, the
        ``pytest.raises`` for the rest.
        """
        _install(workspace)
        (workspace / _VAULT / "data" / "index.bin").write_bytes(b"index\x00")
        _relink(workspace / container, outside, kind)
        before = tree_bytes(outside)
        inside = tree_bytes(workspace)

        if container == _WORKSPACE and not skip:
            # The required-node preflight sees this link first and reports it
            # on the uninstall report rather than raising.
            report = uninstall_run(
                path=workspace, force=True, remove_data=True, skip=set(skip)
            )
            assert report.mcp_sync_failed
            assert any("unsafe directory topology" in e for e in report.mcp_errors)
        else:
            with pytest.raises(LinkedDirectoryError, match=re.escape(container.name)):
                uninstall_run(
                    path=workspace, force=True, remove_data=True, skip=set(skip)
                )

        assert tree_bytes(outside) == before
        assert tree_bytes(workspace) == inside

    def test_the_cli_reports_the_refusal_as_one_failed_envelope(
        self, workspace: Path, outside: Path
    ) -> None:
        _install(workspace)
        _relink(workspace / _VAULT, outside, "symlink")
        before = tree_bytes(outside)

        result = CliRunner().invoke(
            app,
            [
                "uninstall",
                "--target",
                str(workspace),
                "--force",
                "--remove-data",
                "--skip",
                "mcp",
                "--json",
            ],
        )

        assert result.exit_code == 1, result.output
        envelope = json.loads(result.output)
        assert "unsafe directory topology" in json.dumps(envelope)
        assert tree_bytes(outside) == before


class TestEachSinkHoldsItsOwnGround:
    """The mutating steps, called directly on a workspace that changed under them.

    The run-level check is made once, before the first step. These are the
    steps reached after it, so each has to refuse a directory that became a
    link in the meantime rather than trust a check it did not make.
    """

    @pytest.mark.parametrize("kind", LINK_KINDS)
    def test_data_removal_refuses_a_linked_vault(
        self, workspace: Path, outside: Path, kind: str
    ) -> None:
        """``data`` is an ordinary directory; only ``.vault`` above it is not.

        Proven able to fail: with the link check disabled this fails on the
        ``pytest.raises`` below.
        """
        (outside / "data").mkdir(parents=True)
        (outside / "data" / "index.bin").write_bytes(b"index\x00")
        link_directory(workspace / _VAULT, outside, kind)
        before = tree_bytes(outside)
        report = UninstallReport(action="uninstall", target=workspace)

        with pytest.raises(LinkedDirectoryError, match=re.escape(".vault")):
            _remove_data_dir(workspace, False, report)

        assert not report.data_removed
        assert tree_bytes(outside) == before

    @pytest.mark.parametrize("kind", LINK_KINDS)
    def test_data_removal_leaves_a_linked_data_directory_alone(
        self, workspace: Path, outside: Path, kind: str
    ) -> None:
        """Proven able to fail: treating only a symlink as a link lets the
        junction case through to the recursive delete, and it fails on the
        warning assertion.
        """
        (outside / "index.bin").parent.mkdir(parents=True)
        (outside / "index.bin").write_bytes(b"index\x00")
        (workspace / _VAULT).mkdir()
        link_directory(workspace / _VAULT / "data", outside, kind)
        before = tree_bytes(outside)
        report = UninstallReport(action="uninstall", target=workspace)

        _remove_data_dir(workspace, False, report)

        assert any(kind in warning for warning in report.warnings)
        assert not report.data_removed
        assert tree_bytes(outside) == before

    @pytest.mark.parametrize("kind", LINK_KINDS)
    @pytest.mark.parametrize(
        "container", [_WORKSPACE, _WORKSPACE / "rules", _WORKSPACE / "skills"], ids=str
    )
    def test_builtin_removal_refuses_a_linked_container(
        self, workspace: Path, outside: Path, container: Path, kind: str
    ) -> None:
        """Proven able to fail: with the link check disabled this fails on the
        ``pytest.raises`` below.
        """
        _install(workspace)
        _relink(workspace / container, outside, kind)
        before = tree_bytes(outside)
        report = UninstallReport(action="uninstall", target=workspace)

        with pytest.raises(LinkedDirectoryError, match=re.escape(container.name)):
            _remove_candidates(workspace, False, report, skip_mcp=False)

        assert tree_bytes(outside) == before

    @pytest.mark.parametrize("kind", LINK_KINDS)
    def test_sentinel_removal_refuses_a_linked_workspace_directory(
        self, workspace: Path, outside: Path, kind: str
    ) -> None:
        """Proven able to fail: with the link check disabled this fails on the
        ``pytest.raises`` below.
        """
        (outside / "runtime").mkdir(parents=True)
        (outside / "runtime" / "state.json").write_text("{}", encoding="utf-8")
        link_directory(workspace / _WORKSPACE, outside, kind)
        before = tree_bytes(outside)
        report = UninstallReport(action="uninstall", target=workspace)

        with pytest.raises(LinkedDirectoryError, match=re.escape(".vaultspec")):
            _remove_obsolete_sentinels(workspace, False, report)

        assert report.removed == []
        assert tree_bytes(outside) == before

    @pytest.mark.parametrize("kind", LINK_KINDS)
    @pytest.mark.parametrize("nested", [None, "rules"], ids=["target", "rules"])
    def test_seeding_refuses_a_linked_destination(
        self, workspace: Path, outside: Path, nested: str | None, kind: str
    ) -> None:
        """Proven able to fail: with the link check disabled this fails on the
        ``pytest.raises`` below.
        """
        target = workspace / _WORKSPACE
        outside.mkdir()
        if nested is None:
            link_directory(target, outside, kind)
        else:
            target.mkdir()
            link_directory(target / nested, outside, kind)
        written: list[str] = []

        with pytest.raises(LinkedDirectoryError):
            seed_builtins(target, force=True, written=written)

        assert tree_bytes(outside) == {}
        assert not any(relative.startswith("rules/") for relative in written)

    def test_a_dry_run_seed_refuses_a_linked_destination_too(
        self, workspace: Path, outside: Path
    ) -> None:
        outside.mkdir()
        link_directory(workspace / _WORKSPACE, outside, "symlink")

        with pytest.raises(LinkedDirectoryError):
            seed_builtins(workspace / _WORKSPACE, dry_run=True)

    @pytest.mark.parametrize("kind", LINK_KINDS)
    @pytest.mark.parametrize("container", [_VAULT, _WORKSPACE], ids=str)
    def test_bootstrap_does_not_accept_a_link_as_an_existing_directory(
        self, workspace: Path, outside: Path, container: Path, kind: str
    ) -> None:
        """Proven able to fail: with the link check disabled this fails on the
        ``pytest.raises`` below.
        """
        outside.mkdir()
        link_directory(workspace / container, outside, kind)

        with pytest.raises(LinkedDirectoryError, match=re.escape(container.name)):
            _resolve_target(workspace, bootstrap=True)

        assert tree_bytes(outside) == {}


def test_an_unlinked_workspace_still_installs_and_uninstalls(workspace: Path) -> None:
    """The refusal must not cost the ordinary run anything."""
    installed = _install(workspace)
    assert not installed.mcp_sync_failed
    builtins = [workspace / _WORKSPACE / relative for relative in list_builtins()]
    assert all(path.is_file() for path in builtins)
    (workspace / _VAULT / "data" / "index.bin").write_bytes(b"index\x00")
    (workspace / _WORKSPACE / "runtime").mkdir()

    removed = uninstall_run(path=workspace, force=True, remove_data=True)

    assert not removed.mcp_sync_failed
    assert removed.data_removed
    assert not any(path.exists() for path in builtins)
    assert not (workspace / _VAULT / "data").exists()
    assert not (workspace / _WORKSPACE / "runtime").exists()
    assert (workspace / _VAULT).is_dir()
