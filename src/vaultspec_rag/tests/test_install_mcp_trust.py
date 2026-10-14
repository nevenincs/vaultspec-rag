"""The operator's approval of rag's own MCP launch, asked for and recorded at install.

Core refuses to enrol an MCP launch nobody reviewed and refuses to treat a flag
as that review. These tests drive the real install, real core sync and a real
trust record in an isolated home. They prove the gate holds with nobody to ask,
under ``--yes`` and after a decline; and that an attended approval enrols exactly
rag's own definition and no other, is kept until the launch changes, and is never
asked for by a run that enrols nothing.

The mutation each guard catches is named in its own docstring.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Unpack, cast

import pytest
from vaultspec_core.core.enums import InstallMode
from vaultspec_core.core.mcps_trust import trust_file_path

from ..commands._install import (
    _InstallRunOptions,
    install_run,
)

if TYPE_CHECKING:
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
