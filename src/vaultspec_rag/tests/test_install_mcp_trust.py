"""The operator's approval of rag's own MCP launch, asked for and recorded at install.

Core refuses to enrol an MCP launch nobody reviewed and refuses to treat a flag
as that review. These tests drive the real install, real core sync and a real
trust record in an isolated home. They prove the gate holds with nobody to ask,
under ``--yes`` and after a decline; that an attended approval enrols exactly
rag's own definition and no other; and that a linked definition or native config
is approved, and its entries owned, where it really lives, which is what a later
sync of the workspace asks about, as well as where the install holds it while it
runs. Every launch the operator approved there is carried along, and no other.

The mutation each guard catches is named in its own docstring.
"""

from __future__ import annotations

import json
import os
import tomllib
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING, Unpack, cast

import pytest
from vaultspec_core.core.enums import InstallMode, McpScope
from vaultspec_core.core.manifest import write_manifest
from vaultspec_core.core.mcps import ownership_path
from vaultspec_core.core.mcps_trust import trust_file_path

from ..commands._install import (
    _InstallRunOptions,
    _InstallRunRequest,
    _planned_launches,
    install_run,
)
from ._mcp_consent import dry_sync, grant_planned, owned_config_paths, rag_tags

if TYPE_CHECKING:
    from vaultspec_core.core.types import SyncResult

    from ..commands._models import InstallReport

pytestmark = [pytest.mark.unit, pytest.mark.usefixtures("isolated_mcp_trust_home")]

_SOURCE = Path(".vaultspec") / "mcps" / "vaultspec-rag.builtin.json"


def _workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    return ws


def _install(ws: Path, **overrides: Unpack[_InstallRunOptions]) -> InstallReport:
    """Run a network-free install of rag's MCP server in the tool mode."""
    options: _InstallRunOptions = {
        "install_mcp": True,
        "mode": InstallMode.TOOL,
        "configure_torch": False,
        "provision": False,
    }
    options.update(overrides)
    return install_run(path=ws, **options)


class _Operator:
    """An operator at a terminal who answers every question the same way."""

    def __init__(self, *, approves: bool) -> None:
        self.approves = approves
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> bool:
        self.prompts.append(prompt)
        return self.approves


def _providers(report: InstallReport) -> dict[str, dict[str, object]]:
    return cast("dict[str, dict[str, object]]", report.to_dict()["sync_providers"])


def _skipped_for_lack_of_approval(report: InstallReport) -> bool:
    """Whether both providers skipped rag's launch and said how to approve it."""
    providers = _providers(report)
    return all(
        ["vaultspec-rag", "[SKIP]"] in cast("list[object]", providers[host]["items"])
        and any(
            "vaultspec-core spec mcps trust" in str(warning)
            for warning in cast("list[object]", providers[host]["warnings"])
        )
        for host in ("claude", "codex")
    )


def _enrolled(ws: Path) -> tuple[bool, bool]:
    """Whether the Claude and Codex project configs hold rag's server."""
    claude = ws / ".mcp.json"
    codex = ws / ".codex" / "config.toml"
    in_claude = claude.is_file() and "vaultspec-rag" in json.loads(
        claude.read_text(encoding="utf-8")
    ).get("mcpServers", {})
    in_codex = codex.is_file() and "vaultspec-rag" in tomllib.loads(
        codex.read_text(encoding="utf-8")
    ).get("mcp_servers", {})
    return in_claude, in_codex


def _externally_managed(sync: SyncResult) -> list[str]:
    """The warnings of a sync that found an entry it does not own."""
    return [warning for warning in sync.warnings if "externally managed" in warning]


def _builtin_definition() -> str:
    source = files("vaultspec_rag.builtins") / "mcps" / "vaultspec-rag.builtin.json"
    return source.read_text(encoding="utf-8")


class TestApprovalIsAskedOfAnOperator:
    def test_nobody_to_ask_skips_the_launch_and_names_the_grant(
        self, tmp_path: Path
    ) -> None:
        """No callback at all, the shape every unattended run has.

        Mutation it catches: granting without asking, which enrols the launch
        and fails the first assertion.
        """
        ws = _workspace(tmp_path)

        report = _install(ws)

        assert _skipped_for_lack_of_approval(report)
        assert _enrolled(ws) == (False, False)
        assert not trust_file_path().exists()

    def test_assuming_yes_never_asks_and_never_grants(self, tmp_path: Path) -> None:
        """A flag is not a review, even with a live terminal to ask on.

        Mutation it catches: dropping the assume-yes gate. The operator is then
        asked, the prompt list is not empty and the launch is enrolled.
        """
        ws = _workspace(tmp_path)
        operator = _Operator(approves=True)

        report = _install(ws, assume_yes=True, confirm=operator)

        assert operator.prompts == []
        assert _skipped_for_lack_of_approval(report)
        assert _enrolled(ws) == (False, False)
        assert not trust_file_path().exists()

    def test_a_declined_review_skips_the_launch(self, tmp_path: Path) -> None:
        ws = _workspace(tmp_path)
        operator = _Operator(approves=False)

        report = _install(ws, confirm=operator)

        assert len(operator.prompts) == 1
        assert _skipped_for_lack_of_approval(report)
        assert _enrolled(ws) == (False, False)
        assert not trust_file_path().exists()

    def test_an_approved_review_enrols_both_hosts(self, tmp_path: Path) -> None:
        """The prompt shows the exact launch, and a yes enrols it for both hosts.

        Mutation it catches: recording nothing after the yes, which leaves
        both hosts skipped.
        """
        ws = _workspace(tmp_path)
        operator = _Operator(approves=True)

        report = _install(ws, confirm=operator)

        assert not report.mcp_sync_failed
        assert _enrolled(ws) == (True, True)
        assert len(operator.prompts) == 1
        prompt = operator.prompts[0]
        assert "vaultspec-rag[mcp]" in prompt
        assert '"command": "uvx"' in prompt
        assert "vaultspec-rag.builtin.json" in prompt

    def test_the_review_covers_only_rags_own_definition(self, tmp_path: Path) -> None:
        """A sibling definition is never approved on the operator's behalf.

        Mutation it catches: reviewing every planned launch. The sibling is then
        named in the prompt, enrolled, and the last assertion fails.
        """
        ws = _workspace(tmp_path)
        sibling = ws / ".vaultspec" / "mcps" / "operator-extra.builtin.json"
        sibling.parent.mkdir(parents=True)
        sibling.write_text(
            json.dumps({"command": "operator-tool", "args": ["--serve"]}),
            encoding="utf-8",
        )
        operator = _Operator(approves=True)

        report = _install(ws, confirm=operator)

        assert len(operator.prompts) == 1
        prompt = operator.prompts[0]
        assert "operator-tool" not in prompt
        providers = _providers(report)
        for host in ("claude", "codex"):
            items = cast("list[object]", providers[host]["items"])
            assert ["vaultspec-rag", "[ADD]"] in items
            assert ["operator-extra", "[SKIP]"] in items

    def test_a_dry_run_asks_nothing_and_writes_nothing(self, tmp_path: Path) -> None:
        """Previewing never grants, whoever is watching.

        Mutation it catches: reviewing before the dry-run return. The operator
        is asked and the trust record appears.
        """
        ws = _workspace(tmp_path)
        operator = _Operator(approves=True)

        _install(ws, dry_run=True, confirm=operator)

        assert operator.prompts == []
        assert not trust_file_path().exists()
        assert not any(ws.iterdir())

    def test_a_run_without_mcp_asks_nothing(self, tmp_path: Path) -> None:
        ws = _workspace(tmp_path)
        operator = _Operator(approves=True)

        _install(ws, confirm=operator, install_mcp=False)

        assert operator.prompts == []
        assert not trust_file_path().exists()

    def test_a_run_that_skips_core_asks_nothing(self, tmp_path: Path) -> None:
        ws = _workspace(tmp_path)
        operator = _Operator(approves=True)

        _install(ws, confirm=operator, skip={"core"})

        assert operator.prompts == []
        assert not trust_file_path().exists()


class TestApprovalIsKeptUntilTheLaunchChanges:
    def test_an_unchanged_launch_is_not_asked_about_again(self, tmp_path: Path) -> None:
        ws = _workspace(tmp_path)
        assert not _install(ws, confirm=_Operator(approves=True)).mcp_sync_failed
        second = _Operator(approves=True)

        report = _install(ws, upgrade=True, confirm=second)

        assert second.prompts == []
        assert not report.mcp_sync_failed
        assert _enrolled(ws) == (True, True)

    def test_a_changed_definition_is_reviewed_again(self, tmp_path: Path) -> None:
        """An approval covers the exact bytes it was given for, and no others.

        Mutation it catches: treating any approved rag launch as covering a
        changed one. The second install then asks nothing and enrols it.
        """
        ws = _workspace(tmp_path)
        assert not _install(ws, confirm=_Operator(approves=True)).mcp_sync_failed
        source = ws / _SOURCE
        definition = json.loads(source.read_text(encoding="utf-8"))
        definition["command"] = "operator-launcher"
        source.write_text(json.dumps(definition), encoding="utf-8")
        second = _Operator(approves=False)

        report = _install(ws, confirm=second)

        assert len(second.prompts) == 1
        prompt = second.prompts[0]
        assert "operator-launcher" in prompt
        assert _skipped_for_lack_of_approval(report)


class TestApprovalFollowsALinkedLocation:
    """Core binds approval to where a source really lives.

    An install holds a linked definition or native config as a regular copy
    until it commits, so core asks about the copy's path while the install
    syncs and about the link's real target in every later sync. Approval and
    ownership are both keyed that way.
    """

    @staticmethod
    def _link_source(ws: Path) -> Path:
        """Make rag's definition a link to a shared file holding the same bytes."""
        shared = ws / ".vaultspec" / "shared-rag.json"
        link = ws / _SOURCE
        link.parent.mkdir(parents=True)
        shared.write_text(_builtin_definition(), encoding="utf-8")
        link.symlink_to(os.path.relpath(shared, link.parent))
        return link

    @staticmethod
    def _link_claude_config(ws: Path) -> Path:
        """Make the Claude project config a link to a shared file."""
        shared = ws / ".mcp.shared.json"
        shared.write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
        link = ws / ".mcp.json"
        link.symlink_to(shared.name)
        return link

    @pytest.mark.parametrize("link", ["definition", "claude-config"])
    def test_an_approval_given_at_the_real_location_enrols_the_install(
        self, tmp_path: Path, link: str
    ) -> None:
        """The approval an operator gave with core's own command is honoured.

        It is bound to the link's target. The install syncs the link's copy at
        another path, so without carrying the approval there the launch is
        skipped and the install enrols nothing. Mutation it catches: dropping
        the carry into the run, which fails the enrolment assertion.
        """
        ws = _workspace(tmp_path)
        node = (
            self._link_source(ws)
            if link == "definition"
            else self._link_claude_config(ws)
        )
        request = _InstallRunRequest(
            path=ws, install_mcp=True, mode=InstallMode.TOOL, configure_torch=False
        )
        grant_planned(ws, _planned_launches(request, ws))

        report = _install(ws)

        assert not report.mcp_sync_failed
        assert _enrolled(ws) == (True, True)
        assert node.is_symlink()

    def test_a_sibling_approved_at_the_real_location_is_carried_into_the_run(
        self, tmp_path: Path
    ) -> None:
        """Every launch the operator approved is carried, and no other.

        The operator approved one sibling with core's own command, for the
        linked config's real location. The install syncs the config's copy at
        another path, so the approval must follow it there, or core skips a
        launch the operator already reviewed. The second sibling was never
        approved and stays skipped, and the install asks only about rag's own
        launch. Mutations it catches: carrying only rag's own launch leaves the
        approved sibling skipped and fails the enrolment assertion; carrying
        every planned launch enrols the unreviewed one and fails the skip
        assertion.
        """
        ws = _workspace(tmp_path)
        shared = self._link_claude_config(ws).resolve()
        definitions = ws / ".vaultspec" / "mcps"
        definitions.mkdir(parents=True)
        for name in ("operator-extra", "unreviewed-extra"):
            (definitions / f"{name}.builtin.json").write_text(
                json.dumps({"command": f"{name}-tool", "args": ["--serve"]}),
                encoding="utf-8",
            )
        request = _InstallRunRequest(
            path=ws, install_mcp=True, mode=InstallMode.TOOL, configure_torch=False
        )
        grant_planned(
            ws,
            [
                launch
                for launch in _planned_launches(request, ws)
                if launch.name == "operator-extra"
            ],
        )
        operator = _Operator(approves=True)

        report = _install(ws, confirm=operator)

        assert not report.mcp_sync_failed
        assert len(operator.prompts) == 1
        assert "extra" not in operator.prompts[0]
        for host, result in _providers(report).items():
            items = cast("list[object]", result["items"])
            assert ["vaultspec-rag", "[ADD]"] in items, host
            assert ["operator-extra", "[ADD]"] in items, host
            assert ["unreviewed-extra", "[SKIP]"] in items, host
        servers = json.loads(shared.read_text(encoding="utf-8"))["mcpServers"]
        assert set(servers) == {"vaultspec-rag", "operator-extra"}
        refused = [
            warning for warning in dry_sync(ws).warnings if "not approved" in warning
        ]
        assert refused
        assert all("unreviewed-extra" in warning for warning in refused)

    @pytest.mark.parametrize("link", ["definition", "claude-config"])
    def test_a_later_sync_finds_the_launch_approved_and_owned(
        self, tmp_path: Path, link: str
    ) -> None:
        """What the install's own review records is what core asks about next.

        With the link back in place a later sync of the workspace looks at the
        link's target, for the approval and for the ownership of the entry the
        install wrote there. Mutations it catches: recording the approval only
        at the install's copy enrols this run but leaves that later sync
        refusing the launch; leaving the ownership at the copy leaves it
        reporting the entry externally managed, which fails the ownership
        assertions for the linked config and not for the linked definition.
        """
        ws = _workspace(tmp_path)
        node = (
            self._link_source(ws)
            if link == "definition"
            else self._link_claude_config(ws)
        )
        operator = _Operator(approves=True)

        report = _install(ws, confirm=operator)

        assert not report.mcp_sync_failed
        assert len(operator.prompts) == 1
        assert _enrolled(ws) == (True, True)
        assert node.is_symlink()
        later = dry_sync(ws)
        assert not later.errors
        assert not [warning for warning in later.warnings if "not approved" in warning]
        assert not _externally_managed(later)
        assert rag_tags(later) == ["[UNCHANGED]", "[UNCHANGED]"]

    def test_ownership_is_recorded_where_the_config_really_lives(
        self, tmp_path: Path
    ) -> None:
        """No record is left at the install's copy, which no sync looks at again.

        A record at the link's own path would claim ownership of whatever file
        later replaces the link. Mutation it catches: returning a copy of the
        record to the real location instead of moving it, which leaves the
        stale one behind and fails the second assertion.
        """
        ws = _workspace(tmp_path)
        self._link_claude_config(ws)

        assert not _install(ws, confirm=_Operator(approves=True)).mcp_sync_failed

        recorded = owned_config_paths(ws)
        assert ws.resolve() / ".mcp.shared.json" in recorded
        assert ws.resolve() / ".mcp.json" not in recorded

    def test_a_reinstall_over_a_linked_config_still_owns_its_entry(
        self, tmp_path: Path
    ) -> None:
        """Ownership recorded at the real location is the install's own, next time.

        The second install finds the entry owned and leaves it as it is.
        Mutation it catches: not carrying the real location's ownership to the
        install's copy. The sync then meets an entry it does not own, skips it
        as externally managed, and the first assertion fails.
        """
        ws = _workspace(tmp_path)
        self._link_claude_config(ws)
        assert not _install(ws, confirm=_Operator(approves=True)).mcp_sync_failed

        report = _install(ws, upgrade=True)

        assert not report.mcp_sync_failed
        providers = _providers(report)
        assert ["vaultspec-rag", "[UNCHANGED]"] in cast(
            "list[object]", providers["claude"]["items"]
        )
        assert not [
            warning
            for host in providers.values()
            for warning in cast("list[object]", host["warnings"])
            if "externally managed" in str(warning)
        ]
        assert rag_tags(dry_sync(ws)) == ["[UNCHANGED]", "[UNCHANGED]"]

    def test_a_failed_install_over_a_linked_config_restores_ownership_exactly(
        self, tmp_path: Path
    ) -> None:
        """A run that fails after enrolling leaves no ownership behind.

        The hosts are already chosen, so only the install's own rollback can
        undo the ownership. The Codex config cannot be parsed, so the install
        fails after Claude's linked config took rag's entry and its ownership.
        Rollback restores the ownership only when it is exactly what the run is
        expected to have left, and that holds only once the install has returned
        the record to the real location. Mutation it catches: leaving the
        record at the copy, which rollback then refuses to touch as a
        concurrent update and leaves in place.
        """
        ws = _workspace(tmp_path)
        write_manifest(ws, {"claude", "codex"})
        shared = self._link_claude_config(ws).resolve()
        broken = ws / ".codex" / "config.toml"
        broken.parent.mkdir()
        broken.write_text('invalid = "unterminated', encoding="utf-8")
        link_target = os.readlink(ws / ".mcp.json")
        shared_before = shared.read_bytes()

        report = _install(ws, confirm=_Operator(approves=True))

        assert report.mcp_sync_failed
        assert not any("concurrent update preserved" in w for w in report.warnings)
        assert not ownership_path(ws, McpScope.PROJECT).exists()
        assert os.readlink(ws / ".mcp.json") == link_target
        assert shared.read_bytes() == shared_before
        assert broken.read_text(encoding="utf-8") == 'invalid = "unterminated'

    def test_a_failed_reinstall_restores_the_ownership_it_found(
        self, tmp_path: Path
    ) -> None:
        """A run that rewrites owned entries and then fails puts the record back.

        The changed definition makes the install refresh the entry the first
        install wrote, which rewrites its ownership at the link's target, and
        the unparsable Codex config then fails the run. The replay has to have
        found the entry owned to predict that rewrite, or rollback cannot tell
        the install's own write from somebody else's. Mutation it catches:
        leaving the real location's ownership out of the replay, which then
        predicts no rewrite, so rollback treats the refreshed record as a
        concurrent update, leaves it in place and says so.
        """
        ws = _workspace(tmp_path)
        shared = self._link_claude_config(ws).resolve()
        assert not _install(ws, confirm=_Operator(approves=True)).mcp_sync_failed
        ownership = ownership_path(ws, McpScope.PROJECT)
        ownership_before = ownership.read_bytes()
        shared_before = shared.read_bytes()
        source = ws / _SOURCE
        definition = json.loads(source.read_text(encoding="utf-8"))
        definition["command"] = "operator-launcher"
        source.write_text(json.dumps(definition), encoding="utf-8")
        broken = ws / ".codex" / "config.toml"
        broken.write_text('invalid = "unterminated', encoding="utf-8")

        report = _install(ws, confirm=_Operator(approves=True))

        assert report.mcp_sync_failed
        assert not any("concurrent update preserved" in w for w in report.warnings)
        assert ownership.read_bytes() == ownership_before
        assert shared.read_bytes() == shared_before

    def test_a_preview_over_a_linked_config_plans_what_the_install_does(
        self, tmp_path: Path
    ) -> None:
        """The preview finds the entry owned, as the install will.

        Mutation it catches: leaving the real location's ownership out of the
        preview, which then reports the entry skipped as externally managed
        while the install leaves it unchanged, and fails the first assertion.
        """
        ws = _workspace(tmp_path)
        self._link_claude_config(ws)
        assert not _install(ws, confirm=_Operator(approves=True)).mcp_sync_failed

        preview = _install(ws, upgrade=True, dry_run=True)
        applied = _install(ws, upgrade=True)

        assert ["vaultspec-rag", "[UNCHANGED]"] in cast(
            "list[object]", _providers(preview)["claude"]["items"]
        )
        assert _providers(preview) == _providers(applied)
