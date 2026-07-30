"""Real installation integration behavior: preview topology."""

from __future__ import annotations

import json
import os
from pathlib import Path
from threading import Event, Thread
from typing import cast

import pytest
from vaultspec_core.core.enums import (
    InstallMode,
)

from ...commands._uninstall import uninstall_run
from ._install_helpers import (
    _CONSUMER_PYPROJECT,
    _RAG_MCP_REL,
    _RAG_NON_MCP_BUILTIN_REL,
    _REQUIRED_MCP_RELATIVES,
    _install,
    _node_signature,
    create_windows_junction,
    read_codex_mcp,
    read_mcp_json,
    required_mcp_transaction_inventory,
    workspace_inventory,
)

pytestmark = [pytest.mark.integration]


class TestInstallPreviewTopology:
    @pytest.mark.parametrize("relative", _REQUIRED_MCP_RELATIVES)
    def test_required_relative_file_link_preserves_preview_apply_parity(
        self,
        fresh_workspace: Path,
        relative: Path,
    ) -> None:
        _install(fresh_workspace, mode=InstallMode.TOOL)
        node = fresh_workspace / relative
        linked_target = node.with_name(f"{node.name}.operator")
        node.replace(linked_target)
        node.symlink_to(linked_target.name)
        link_signature = _node_signature(node)
        target_before_preview = linked_target.read_bytes()

        preview = _install(
            fresh_workspace,
            dry_run=True,
            upgrade=True,
            mode=InstallMode.TOOL,
        )

        assert not preview.mcp_sync_failed
        assert _node_signature(node) == link_signature
        assert linked_target.read_bytes() == target_before_preview
        applied = _install(
            fresh_workspace,
            upgrade=True,
            mode=InstallMode.TOOL,
        )
        assert not applied.mcp_sync_failed
        assert (
            preview.to_dict()["sync_providers"] == applied.to_dict()["sync_providers"]
        )
        assert _node_signature(node) == link_signature
        assert node.read_bytes() == linked_target.read_bytes()

        repeated = _install(
            fresh_workspace,
            upgrade=True,
            mode=InstallMode.TOOL,
        )

        assert not repeated.mcp_sync_failed
        assert _node_signature(node) == link_signature
        assert linked_target.is_file()
        assert node.read_bytes() == linked_target.read_bytes()

    @pytest.mark.parametrize("relative", _REQUIRED_MCP_RELATIVES)
    def test_required_relative_file_link_publishes_logical_delta_to_target(
        self,
        fresh_workspace: Path,
        relative: Path,
    ) -> None:
        _install(fresh_workspace, mode=InstallMode.TOOL)
        node = fresh_workspace / relative
        linked_target = node.with_name(f"{node.name}.operator")
        node.replace(linked_target)
        node.symlink_to(linked_target.name)
        link_signature = _node_signature(node)

        if relative == Path(".mcp.json"):
            linked_target.write_text(
                linked_target.read_text(encoding="utf-8").replace(
                    '"command": "uvx"',
                    '"command": "operator-drift"',
                    1,
                ),
                encoding="utf-8",
            )
        elif relative == Path(".codex") / "config.toml":
            linked_target.write_text(
                linked_target.read_text(encoding="utf-8").replace(
                    'command = "uvx"',
                    'command = "operator-drift"',
                    1,
                ),
                encoding="utf-8",
            )
        elif relative == Path(".vaultspec") / "mcp-ownership.json":
            state = cast(
                "dict[str, dict[str, object]]",
                json.loads(linked_target.read_text(encoding="utf-8")),
            )
            del state["targets"]["claude:project"]
            linked_target.write_text(
                json.dumps(state, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        elif relative == Path(".vaultspec") / "providers.json":
            manifest = cast(
                "dict[str, object]",
                json.loads(linked_target.read_text(encoding="utf-8")),
            )
            manifest["installed"] = []
            linked_target.write_text(
                json.dumps(manifest, indent=2) + "\n",
                encoding="utf-8",
            )
        elif relative == Path(".vaultspec") / "workspace.json":
            workspace = cast(
                "dict[str, dict[str, dict[str, object]]]",
                json.loads(linked_target.read_text(encoding="utf-8")),
            )
            workspace["packages"]["vaultspec-rag"]["install_mode"] = "dependency"
            linked_target.write_text(
                json.dumps(workspace, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        else:
            definition = cast(
                "dict[str, object]",
                json.loads(linked_target.read_text(encoding="utf-8")),
            )
            definition["_vaultspec_mode_tool_spec"] = "operator-drift"
            linked_target.write_text(
                json.dumps(definition, indent=2) + "\n",
                encoding="utf-8",
            )
        drifted = linked_target.read_bytes()

        preview = _install(
            fresh_workspace,
            dry_run=True,
            upgrade=True,
            force=True,
            mode=InstallMode.TOOL,
        )
        assert _node_signature(node) == link_signature
        assert linked_target.read_bytes() == drifted
        applied = _install(
            fresh_workspace,
            upgrade=True,
            force=True,
            mode=InstallMode.TOOL,
        )

        assert not preview.mcp_sync_failed
        assert not applied.mcp_sync_failed
        assert (
            preview.to_dict()["sync_providers"] == applied.to_dict()["sync_providers"]
        )
        assert _node_signature(node) == link_signature
        assert linked_target.read_bytes() != drifted
        assert node.read_bytes() == linked_target.read_bytes()
        repeated = _install(
            fresh_workspace,
            upgrade=True,
            force=True,
            mode=InstallMode.TOOL,
        )
        assert not repeated.mcp_sync_failed
        assert _node_signature(node) == link_signature
        assert node.read_bytes() == linked_target.read_bytes()

    def test_failed_native_reconciliation_restores_link_and_target_exactly(
        self,
        fresh_workspace: Path,
    ) -> None:
        _install(fresh_workspace, mode=InstallMode.TOOL)
        claude = fresh_workspace / ".mcp.json"
        linked_target = fresh_workspace / ".mcp.operator.json"
        claude.replace(linked_target)
        claude.symlink_to(linked_target.name)
        linked_target.write_text(
            linked_target.read_text(encoding="utf-8").replace(
                '"command": "uvx"',
                '"command": "operator-drift"',
                1,
            ),
            encoding="utf-8",
        )
        codex = fresh_workspace / ".codex" / "config.toml"
        codex.write_text('invalid = "unterminated', encoding="utf-8")
        signature = _node_signature(claude)
        target_before = linked_target.read_bytes()
        codex_before = codex.read_bytes()

        report = _install(
            fresh_workspace,
            upgrade=True,
            force=True,
            mode=InstallMode.TOOL,
        )

        assert report.mcp_sync_failed
        assert _node_signature(claude) == signature
        assert linked_target.read_bytes() == target_before
        assert codex.read_bytes() == codex_before

    def test_failed_native_reconciliation_restores_all_regular_required_nodes(
        self,
        fresh_workspace: Path,
    ) -> None:
        _install(fresh_workspace, mode=InstallMode.TOOL)
        codex = fresh_workspace / ".codex" / "config.toml"
        codex.write_text('invalid = "unterminated', encoding="utf-8")
        before = required_mcp_transaction_inventory(fresh_workspace)

        report = _install(
            fresh_workspace,
            upgrade=True,
            force=True,
            mode=InstallMode.TOOL,
        )

        assert report.mcp_sync_failed
        assert required_mcp_transaction_inventory(fresh_workspace) == before
        assert codex.read_bytes() == b'invalid = "unterminated'

    def test_partial_ownership_update_uses_real_root_replay_token(
        self,
        fresh_workspace: Path,
    ) -> None:
        _install(fresh_workspace, mode=InstallMode.TOOL)
        ownership = fresh_workspace / ".vaultspec" / "mcp-ownership.json"
        state = cast(
            "dict[str, dict[str, object]]",
            json.loads(ownership.read_text(encoding="utf-8")),
        )
        del state["targets"]["claude:project"]
        ownership.write_text(
            json.dumps(state, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        codex = fresh_workspace / ".codex" / "config.toml"
        codex.write_text('invalid = "unterminated', encoding="utf-8")
        before = required_mcp_transaction_inventory(fresh_workspace)

        report = _install(
            fresh_workspace,
            upgrade=True,
            force=True,
            mode=InstallMode.TOOL,
        )

        assert report.mcp_sync_failed
        assert required_mcp_transaction_inventory(fresh_workspace) == before
        assert not any(
            "mcp-ownership.json: concurrent update preserved" in warning
            for warning in report.warnings
        )

    def test_mode_migration_finishes_before_non_mcp_provider_sync(
        self,
        fresh_workspace: Path,
    ) -> None:
        (fresh_workspace / "pyproject.toml").write_text(
            _CONSUMER_PYPROJECT,
            encoding="utf-8",
        )
        _install(fresh_workspace, mode=InstallMode.DEPENDENCY)
        documents = (
            fresh_workspace / "CLAUDE.md",
            fresh_workspace / "AGENTS.md",
        )
        for document in documents:
            document.unlink(missing_ok=True)
        codex = fresh_workspace / ".codex" / "config.toml"
        documents_seen = Event()
        stop = Event()

        def corrupt_codex_after_documents() -> None:
            while not stop.wait(0.001):
                if all(document.is_file() for document in documents):
                    codex.write_text('invalid = "unterminated', encoding="utf-8")
                    documents_seen.set()
                    return

        watcher = Thread(target=corrupt_codex_after_documents, daemon=True)
        watcher.start()
        try:
            report = _install(
                fresh_workspace,
                upgrade=True,
                force=False,
                mode=InstallMode.TOOL,
            )
            documents_seen.wait(2)
        finally:
            stop.set()
            watcher.join(timeout=2)

        assert documents_seen.is_set()
        assert not report.mcp_sync_failed
        assert all(document.is_file() for document in documents)

    def test_all_canonical_source_links_have_preview_apply_parity(
        self,
        fresh_workspace: Path,
    ) -> None:
        _install(fresh_workspace, mode=InstallMode.TOOL)
        source_dir = fresh_workspace / ".vaultspec" / "mcps"
        linked_target = fresh_workspace / ".vaultspec" / "operator-extra.json"
        linked_target.write_bytes((fresh_workspace / _RAG_MCP_REL).read_bytes())
        source = source_dir / "operator-extra.builtin.json"
        source.symlink_to(os.path.relpath(linked_target, source.parent))
        source_signature = _node_signature(source)
        target_before = linked_target.read_bytes()

        preview = _install(
            fresh_workspace,
            dry_run=True,
            upgrade=True,
            mode=InstallMode.TOOL,
        )
        applied = _install(
            fresh_workspace,
            upgrade=True,
            mode=InstallMode.TOOL,
        )

        assert not preview.mcp_sync_failed
        assert not applied.mcp_sync_failed
        assert (
            preview.to_dict()["sync_providers"] == applied.to_dict()["sync_providers"]
        )
        for provider in ("claude", "codex"):
            assert ["operator-extra", "[ADD]"] in preview.to_dict()["sync_providers"][
                provider
            ]["items"]
        assert _node_signature(source) == source_signature
        assert linked_target.read_bytes() == target_before

    @pytest.mark.parametrize(
        "link_case",
        ["outside-relative", "broken-relative", "absolute", "chained"],
    )
    def test_unsafe_extra_canonical_source_link_fails_with_parity(
        self,
        fresh_workspace: Path,
        tmp_path: Path,
        link_case: str,
    ) -> None:
        _install(fresh_workspace, mode=InstallMode.TOOL)
        source = fresh_workspace / ".vaultspec" / "mcps" / "operator-extra.builtin.json"
        local_target = fresh_workspace / ".vaultspec" / "operator-extra.json"
        local_target.write_bytes((fresh_workspace / _RAG_MCP_REL).read_bytes())
        if link_case == "outside-relative":
            target = tmp_path / "outside-operator-extra.json"
            target.write_bytes(local_target.read_bytes())
            link_text = os.path.relpath(target, source.parent)
        elif link_case == "absolute":
            target = local_target
            link_text = str(target.resolve())
        elif link_case == "chained":
            target = local_target
            intermediate = source.parent / "operator-extra.intermediate.json"
            intermediate.symlink_to(os.path.relpath(target, intermediate.parent))
            link_text = intermediate.name
        else:
            target = None
            link_text = "missing-operator-extra.json"
        source.symlink_to(link_text)
        before = workspace_inventory(fresh_workspace)

        preview = _install(fresh_workspace, dry_run=True, upgrade=True)
        applied = _install(fresh_workspace, upgrade=True)

        assert preview.mcp_sync_failed and applied.mcp_sync_failed
        assert preview.mcp_errors == applied.mcp_errors
        assert workspace_inventory(fresh_workspace) == before

    @pytest.mark.parametrize("linked_target", [False, True])
    def test_required_hardlink_topology_fails_closed_before_mutation(
        self,
        fresh_workspace: Path,
        linked_target: bool,
    ) -> None:
        _install(fresh_workspace, mode=InstallMode.TOOL)
        node = fresh_workspace / ".mcp.json"
        if linked_target:
            target = fresh_workspace / ".mcp.operator.json"
            node.replace(target)
            alias = fresh_workspace / ".mcp.operator.alias.json"
            os.link(target, alias)
            node.symlink_to(target.name)
        else:
            target = node
            alias = fresh_workspace / ".mcp.alias.json"
            os.link(target, alias)
        before = workspace_inventory(fresh_workspace)
        inode_pair = (target.stat().st_ino, alias.stat().st_ino)

        preview = _install(fresh_workspace, dry_run=True, upgrade=True)
        applied = _install(fresh_workspace, upgrade=True)

        assert preview.mcp_sync_failed and applied.mcp_sync_failed
        assert preview.mcp_errors == applied.mcp_errors
        assert "hard links" in " ".join(preview.mcp_errors)
        assert workspace_inventory(fresh_workspace) == before
        assert (target.stat().st_ino, alias.stat().st_ino) == inode_pair

    def test_pre_materialization_race_preserves_newer_required_bytes(
        self,
        fresh_workspace: Path,
    ) -> None:
        from ...commands._mcp_topology import inspect_required_mcp_topology

        _install(fresh_workspace, mode=InstallMode.TOOL)
        topology = inspect_required_mcp_topology(fresh_workspace)
        node = fresh_workspace / ".mcp.json"
        concurrent = b'{"operator": "newer"}\n'
        node.write_bytes(concurrent)

        with pytest.raises(OSError, match="changed during transaction"):
            topology.materialize()

        assert node.read_bytes() == concurrent

    def test_in_flight_regular_node_race_is_preserved_on_rollback(
        self,
        fresh_workspace: Path,
    ) -> None:
        from ...commands._mcp_topology import inspect_required_mcp_topology

        _install(fresh_workspace, mode=InstallMode.TOOL)
        topology = inspect_required_mcp_topology(fresh_workspace)
        topology.materialize()
        node = fresh_workspace / ".mcp.json"
        concurrent = b'{"operator": "newer"}\n'
        node.write_bytes(concurrent)

        errors = topology.finish(commit=False)

        assert errors
        assert "concurrent update preserved" in " ".join(errors)
        assert node.read_bytes() == concurrent

    def test_post_mutation_cas_preserves_later_regular_node_update(
        self,
        fresh_workspace: Path,
        tmp_path: Path,
    ) -> None:
        from ...commands._mcp_topology import inspect_required_mcp_topology

        _install(fresh_workspace, mode=InstallMode.TOOL)
        topology = inspect_required_mcp_topology(fresh_workspace)
        topology.materialize()
        node = fresh_workspace / ".mcp.json"
        projection = tmp_path / "replay"
        topology.populate_projection(projection)
        (projection / ".mcp.json").write_bytes(b'{"transaction": "authored"}\n')
        topology.capture_expected_projection(projection)
        node.write_bytes(b'{"transaction": "authored"}\n')
        concurrent = b'{"operator": "newer"}\n'
        node.write_bytes(concurrent)

        errors = topology.finish(commit=False)

        assert errors
        assert "concurrent update preserved" in " ".join(errors)
        assert node.read_bytes() == concurrent

    def test_replay_token_preserves_pre_rollback_atomic_operator_save(
        self,
        fresh_workspace: Path,
        tmp_path: Path,
    ) -> None:
        from ...commands._mcp_topology import inspect_required_mcp_topology

        _install(fresh_workspace, mode=InstallMode.TOOL)
        topology = inspect_required_mcp_topology(fresh_workspace)
        projection = tmp_path / "replay"
        topology.populate_projection(projection)
        (projection / ".mcp.json").write_bytes(b'{"transaction": "authored"}\n')
        topology.capture_expected_projection(projection)
        node = fresh_workspace / ".mcp.json"
        replacement = fresh_workspace / ".operator-save.json"
        concurrent = b'{"operator": "atomic-newer"}\n'
        replacement.write_bytes(concurrent)
        os.replace(replacement, node)

        errors = topology.finish(commit=False)

        assert errors
        assert node.read_bytes() == concurrent

    def test_replay_token_preserves_operator_created_absent_node(
        self,
        fresh_workspace: Path,
        tmp_path: Path,
    ) -> None:
        from ...commands._mcp_topology import inspect_required_mcp_topology

        topology = inspect_required_mcp_topology(fresh_workspace)
        projection = tmp_path / "replay"
        topology.populate_projection(projection)
        (projection / ".mcp.json").write_bytes(b'{"transaction": "authored"}\n')
        topology.capture_expected_projection(projection)
        node = fresh_workspace / ".mcp.json"
        concurrent = b'{"operator": "created-newer"}\n'
        node.write_bytes(concurrent)

        errors = topology.finish(commit=False)

        assert errors
        assert node.read_bytes() == concurrent

    def test_replay_token_restores_same_inode_transaction_publication(
        self,
        fresh_workspace: Path,
        tmp_path: Path,
    ) -> None:
        from ...commands._mcp_topology import inspect_required_mcp_topology

        _install(fresh_workspace, mode=InstallMode.TOOL)
        topology = inspect_required_mcp_topology(fresh_workspace)
        projection = tmp_path / "replay"
        topology.populate_projection(projection)
        node = fresh_workspace / ".mcp.json"
        original = node.read_bytes()
        authored = b'{"transaction": "copy-fallback"}\n'
        (projection / ".mcp.json").write_bytes(authored)
        topology.capture_expected_projection(projection)
        inode = node.stat().st_ino
        node.write_bytes(authored)
        assert node.stat().st_ino == inode

        errors = topology.finish(commit=False)

        assert not errors
        assert node.read_bytes() == original

    def test_replay_token_restores_link_after_immediate_materialized_abort(
        self,
        fresh_workspace: Path,
        tmp_path: Path,
    ) -> None:
        from ...commands._mcp_topology import inspect_required_mcp_topology

        _install(fresh_workspace, mode=InstallMode.TOOL)
        node = fresh_workspace / ".mcp.json"
        target = fresh_workspace / ".mcp.operator.json"
        node.replace(target)
        node.symlink_to(target.name)
        signature = _node_signature(node)
        original = target.read_bytes()
        topology = inspect_required_mcp_topology(fresh_workspace)
        projection = tmp_path / "replay"
        topology.populate_projection(projection)
        (projection / ".mcp.json").write_bytes(b'{"transaction": "authored"}\n')
        topology.capture_expected_projection(projection)

        topology.materialize()
        errors = topology.finish(commit=False)

        assert not errors
        assert _node_signature(node) == signature
        assert node.read_bytes() == original

    def test_materialize_write_failure_restores_just_removed_link(
        self,
        fresh_workspace: Path,
    ) -> None:
        from ...commands._mcp_topology import inspect_required_mcp_topology

        source_dir = fresh_workspace / ".vaultspec" / "mcps"
        source_dir.mkdir(parents=True)
        target = fresh_workspace / ".vaultspec" / "operator-extra.json"
        target.write_bytes(b'{"command": "operator", "args": []}\n')
        source = source_dir / ("operator-" + "x" * 225 + ".json")
        source.symlink_to(os.path.relpath(target, source.parent))
        signature = _node_signature(source)
        topology = inspect_required_mcp_topology(fresh_workspace)

        with pytest.raises(OSError):
            topology.materialize()

        assert _node_signature(source) == signature
        assert source.read_bytes() == target.read_bytes()

    def test_link_target_race_is_preserved_on_commit_refusal(
        self,
        fresh_workspace: Path,
    ) -> None:
        from ...commands._mcp_topology import inspect_required_mcp_topology

        _install(fresh_workspace, mode=InstallMode.TOOL)
        node = fresh_workspace / ".mcp.json"
        target = fresh_workspace / ".mcp.operator.json"
        node.replace(target)
        node.symlink_to(target.name)
        link_signature = _node_signature(node)
        topology = inspect_required_mcp_topology(fresh_workspace)
        topology.materialize()
        concurrent = b'{"operator": "newer"}\n'
        target.write_bytes(concurrent)

        errors = topology.finish(commit=True)

        assert errors
        assert target.read_bytes() == concurrent
        assert _node_signature(node) == link_signature

    def test_failed_no_mcp_restores_dependency_placement_exactly(
        self,
        fresh_workspace: Path,
    ) -> None:
        pyproject = fresh_workspace / "pyproject.toml"
        pyproject.write_text(_CONSUMER_PYPROJECT, encoding="utf-8")
        _install(fresh_workspace, mode=InstallMode.DEPENDENCY)
        codex = fresh_workspace / ".codex" / "config.toml"
        codex.write_text('invalid = "unterminated', encoding="utf-8")
        before = required_mcp_transaction_inventory(fresh_workspace)

        report = _install(
            fresh_workspace,
            upgrade=True,
            force=True,
            install_mcp=False,
            mode=InstallMode.DEPENDENCY,
        )

        assert report.mcp_sync_failed
        assert required_mcp_transaction_inventory(fresh_workspace) == before

    @pytest.mark.parametrize("operation", ["no-mcp", "uninstall"])
    def test_unrelated_safe_linked_source_does_not_block_disenrollment(
        self,
        fresh_workspace: Path,
        operation: str,
    ) -> None:
        _install(fresh_workspace, mode=InstallMode.TOOL)
        source = fresh_workspace / ".vaultspec" / "mcps" / "operator-extra.builtin.json"
        target = fresh_workspace / ".vaultspec" / "operator-extra.json"
        target.write_bytes((fresh_workspace / _RAG_MCP_REL).read_bytes())
        source.symlink_to(os.path.relpath(target, source.parent))
        enrolled = _install(fresh_workspace, upgrade=True)
        assert not enrolled.mcp_sync_failed
        signature = _node_signature(source)
        target_before = target.read_bytes()

        if operation == "no-mcp":
            preview = _install(
                fresh_workspace,
                dry_run=True,
                upgrade=True,
                install_mcp=False,
            )
            applied = _install(
                fresh_workspace,
                upgrade=True,
                install_mcp=False,
            )
        else:
            preview = uninstall_run(path=fresh_workspace, force=False)
            applied = uninstall_run(path=fresh_workspace, force=True)

        assert not preview.mcp_sync_failed
        assert not applied.mcp_sync_failed
        assert _node_signature(source) == signature
        assert target.read_bytes() == target_before
        assert "vaultspec-rag" not in read_mcp_json(fresh_workspace)["mcpServers"]
        assert "vaultspec-rag" not in read_codex_mcp(fresh_workspace)

    @pytest.mark.parametrize(
        "container_relative",
        [Path(".vaultspec"), Path(".codex"), Path(".vaultspec") / "mcps"],
    )
    def test_linked_required_container_fails_before_lifecycle_mutation(
        self,
        fresh_workspace: Path,
        container_relative: Path,
    ) -> None:
        _install(fresh_workspace, mode=InstallMode.TOOL)
        container = fresh_workspace / container_relative
        linked_target = container.with_name(f"{container.name}.operator")
        container.replace(linked_target)
        container.symlink_to(linked_target.name, target_is_directory=True)
        signature = _node_signature(container)
        target_before = workspace_inventory(linked_target)

        preview = _install(fresh_workspace, dry_run=True, upgrade=True)
        applied = _install(fresh_workspace, upgrade=True)

        assert preview.mcp_sync_failed and applied.mcp_sync_failed
        assert preview.mcp_errors == applied.mcp_errors
        assert _node_signature(container) == signature
        assert workspace_inventory(linked_target) == target_before

    @pytest.mark.parametrize("relative", _REQUIRED_MCP_RELATIVES)
    @pytest.mark.parametrize(
        "link_case",
        ["outside-relative", "broken-relative", "absolute"],
    )
    def test_unsafe_required_file_link_fails_before_lifecycle_mutation(
        self,
        fresh_workspace: Path,
        tmp_path: Path,
        relative: Path,
        link_case: str,
    ) -> None:
        _install(fresh_workspace, mode=InstallMode.TOOL)
        node = fresh_workspace / relative
        original = node.read_bytes()
        preserved = node.with_name(f"{node.name}.preserved")
        node.replace(preserved)
        if link_case == "outside-relative":
            linked_target = tmp_path / f"outside-{relative.name}"
            linked_target.write_bytes(original)
            link_text = os.path.relpath(linked_target, node.parent)
        elif link_case == "absolute":
            linked_target = preserved
            link_text = str(linked_target.resolve())
        else:
            linked_target = None
            link_text = f"missing-{relative.name}"
        node.symlink_to(link_text)
        signature = _node_signature(node)
        preserved_before = preserved.read_bytes()
        outside_before = (
            linked_target.read_bytes() if linked_target is not None else None
        )

        preview = _install(
            fresh_workspace,
            dry_run=True,
            upgrade=True,
            mode=InstallMode.TOOL,
        )
        applied = _install(
            fresh_workspace,
            upgrade=True,
            mode=InstallMode.TOOL,
        )

        for report in (preview, applied):
            assert report.mcp_sync_failed
            assert report.mcp_errors
            assert not report.seeded
            assert not report.sync_results
        assert preview.mcp_errors == applied.mcp_errors
        assert _node_signature(node) == signature
        assert preserved.read_bytes() == preserved_before
        if linked_target is not None:
            assert linked_target.read_bytes() == outside_before

    def test_required_links_cannot_alias_one_target(
        self,
        fresh_workspace: Path,
    ) -> None:
        _install(fresh_workspace, mode=InstallMode.TOOL)
        claude = fresh_workspace / ".mcp.json"
        codex = fresh_workspace / ".codex" / "config.toml"
        shared = fresh_workspace / "shared-required-target"
        shared.write_bytes(claude.read_bytes())
        claude.unlink()
        codex.unlink()
        claude.symlink_to(shared.name)
        codex.symlink_to(os.path.relpath(shared, codex.parent))
        signatures = (_node_signature(claude), _node_signature(codex))
        shared_before = shared.read_bytes()

        preview = _install(fresh_workspace, dry_run=True, upgrade=True)
        applied = _install(fresh_workspace, upgrade=True)

        assert preview.mcp_sync_failed and applied.mcp_sync_failed
        assert preview.mcp_errors == applied.mcp_errors
        assert "aliases required node" in " ".join(preview.mcp_errors)
        assert (_node_signature(claude), _node_signature(codex)) == signatures
        assert shared.read_bytes() == shared_before

    def test_required_link_cannot_overlap_another_required_node(
        self,
        fresh_workspace: Path,
    ) -> None:
        _install(fresh_workspace, mode=InstallMode.TOOL)
        ownership = fresh_workspace / ".vaultspec" / "mcp-ownership.json"
        providers = fresh_workspace / ".vaultspec" / "providers.json"
        ownership.unlink()
        ownership.symlink_to(providers.name)
        signature = _node_signature(ownership)
        providers_before = providers.read_bytes()

        preview = _install(fresh_workspace, dry_run=True, upgrade=True)
        applied = _install(fresh_workspace, upgrade=True)

        assert preview.mcp_sync_failed and applied.mcp_sync_failed
        assert preview.mcp_errors == applied.mcp_errors
        assert "overlaps a required MCP node" in " ".join(preview.mcp_errors)
        assert _node_signature(ownership) == signature
        assert providers.read_bytes() == providers_before

    @pytest.mark.parametrize(
        ("target_relative", "create_target"),
        [
            (_RAG_NON_MCP_BUILTIN_REL, False),
            (
                Path(".claude") / "rules" / "vaultspec-rag.builtin.md",
                False,
            ),
            (Path(".vaultspec") / "rules" / ".gitignore", False),
            (Path(".gitignore"), True),
            (Path(".claude") / "settings.json.lock", True),
        ],
    )
    def test_required_link_cannot_overlap_any_lifecycle_output(
        self,
        fresh_workspace: Path,
        target_relative: Path,
        create_target: bool,
    ) -> None:
        installed = _install(fresh_workspace, mode=InstallMode.TOOL)
        assert not installed.mcp_sync_failed
        node = fresh_workspace / ".mcp.json"
        linked_target = fresh_workspace / target_relative
        if create_target:
            linked_target.parent.mkdir(parents=True, exist_ok=True)
            linked_target.write_bytes(b"operator-lock-state\x00")
        assert linked_target.is_file()
        node.unlink()
        node.symlink_to(os.path.relpath(linked_target, node.parent))
        signature = _node_signature(node)
        target_before = linked_target.read_bytes()

        preview = _install(fresh_workspace, dry_run=True, upgrade=True)
        applied = _install(fresh_workspace, upgrade=True)

        for report in (preview, applied):
            assert report.mcp_sync_failed
            assert "overlaps a lifecycle output" in " ".join(report.mcp_errors)
            assert not report.seeded
            assert not report.sync_results
        assert preview.mcp_errors == applied.mcp_errors
        assert _node_signature(node) == signature
        assert linked_target.read_bytes() == target_before

    def test_uninstall_rejects_required_link_to_bundled_lifecycle_output(
        self,
        fresh_workspace: Path,
    ) -> None:
        installed = _install(fresh_workspace, mode=InstallMode.TOOL)
        assert not installed.mcp_sync_failed
        node = fresh_workspace / ".mcp.json"
        linked_target = fresh_workspace / _RAG_NON_MCP_BUILTIN_REL
        node.unlink()
        node.symlink_to(os.path.relpath(linked_target, node.parent))
        signature = _node_signature(node)
        target_before = linked_target.read_bytes()

        preview = uninstall_run(path=fresh_workspace, force=False)
        applied = uninstall_run(path=fresh_workspace, force=True)

        for report in (preview, applied):
            assert report.mcp_sync_failed
            assert "overlaps a lifecycle output" in " ".join(report.mcp_errors)
            assert not report.removed
            assert not report.sync_results
        assert preview.mcp_errors == applied.mcp_errors
        assert _node_signature(node) == signature
        assert linked_target.read_bytes() == target_before

    def test_cli_reports_unsafe_required_topology_with_nonzero_json(
        self,
        fresh_workspace: Path,
    ) -> None:
        from typer.testing import CliRunner

        from ...cli import app

        _install(fresh_workspace, mode=InstallMode.TOOL)
        claude = fresh_workspace / ".mcp.json"
        preserved = fresh_workspace / ".mcp.preserved.json"
        claude.replace(preserved)
        claude.symlink_to("missing-required-target")
        signature = _node_signature(claude)
        preserved_before = preserved.read_bytes()

        result = CliRunner().invoke(
            app,
            [
                "install",
                "--target",
                str(fresh_workspace),
                "--upgrade",
                "--dry-run",
                "--no-provision",
                "--no-torch-config",
                "--mcp",
                "--json",
            ],
            catch_exceptions=False,
        )

        assert result.exit_code == 2, result.output
        report = cast("dict[str, object]", json.loads(result.output))
        assert report["mcp_failed"] is True
        assert "required MCP topology preflight failed" in " ".join(
            cast("list[str]", report["mcp_errors"])
        )
        assert _node_signature(claude) == signature
        assert preserved.read_bytes() == preserved_before

    if os.name == "nt":

        @pytest.mark.parametrize("relative", _REQUIRED_MCP_RELATIVES)
        def test_required_junction_fails_before_lifecycle_mutation(
            self,
            fresh_workspace: Path,
            tmp_path: Path,
            relative: Path,
        ) -> None:
            _install(fresh_workspace, mode=InstallMode.TOOL)
            node = fresh_workspace / relative
            preserved = node.with_name(f"{node.name}.preserved")
            node.replace(preserved)
            junction_target = tmp_path / f"junction-{relative.name}"
            junction_target.mkdir()
            (junction_target / "sentinel").write_bytes(b"operator-owned\x00")
            target_before = workspace_inventory(junction_target)
            create_windows_junction(node, junction_target)
            signature = _node_signature(node)

            preview = _install(fresh_workspace, dry_run=True, upgrade=True)
            applied = _install(fresh_workspace, upgrade=True)

            assert preview.mcp_sync_failed and applied.mcp_sync_failed
            assert preview.mcp_errors == applied.mcp_errors
            assert _node_signature(node) == signature
            assert workspace_inventory(junction_target) == target_before

        @pytest.mark.parametrize(
            "container_relative",
            [Path(".vaultspec"), Path(".codex"), Path(".vaultspec") / "mcps"],
        )
        def test_required_junction_container_fails_before_lifecycle_mutation(
            self,
            fresh_workspace: Path,
            tmp_path: Path,
            container_relative: Path,
        ) -> None:
            _install(fresh_workspace, mode=InstallMode.TOOL)
            container = fresh_workspace / container_relative
            preserved = container.with_name(f"{container.name}.preserved")
            container.replace(preserved)
            junction_target = tmp_path / f"junction-{container.name}"
            preserved.replace(junction_target)
            target_before = workspace_inventory(junction_target)
            create_windows_junction(container, junction_target)
            signature = _node_signature(container)

            preview = _install(fresh_workspace, dry_run=True, upgrade=True)
            applied = _install(fresh_workspace, upgrade=True)

            assert preview.mcp_sync_failed and applied.mcp_sync_failed
            assert preview.mcp_errors == applied.mcp_errors
            assert _node_signature(container) == signature
            assert workspace_inventory(junction_target) == target_before
