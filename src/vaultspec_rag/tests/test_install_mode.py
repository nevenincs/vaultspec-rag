"""Unit tests for install-time provisioning-mode wiring (install-parity W02).

Exercises the real install orchestration (:func:`install_run`) over the real
filesystem with no mocks and no network: provisioning and torch config are opted
out, while the optional MCP extra is reconciled directly in the temporary
project without invoking a package manager. The run seeds rag's bundled tree,
invokes core's real ``sync_provider``, and persists and renders rag's mode through
core's shared ``workspace_mode`` machinery without touching the GPU or network.

The three-placement model (``tool`` / ``dependency`` / ``dev``) is owned by
vaultspec-core; rag adopts it by naming ``vaultspec-rag`` as the package core's
resolver, per-package declaration writer, and MCP renderer operate on. These
tests assert the rag-side contract: rag's own entry in the shared
``.vaultspec/workspace.json`` map, rag's ``.mcp.json`` launch shape rendered at
rag's own mode, sibling-package preservation in a mixed configuration, detection
for the rag distribution, upgrade-time inference, the moment-of-choice
dependency-leak advisory, and the orthogonality of the ``--local-only`` backend
marker.

See the plan ``2026-07-14-install-parity-plan`` (W02.P06) and the
``2026-07-14-install-parity-adr``.
"""

from __future__ import annotations

import json
from importlib.resources import files
from typing import TYPE_CHECKING, cast

import pytest
from vaultspec_core.core.commands import (  # pyright: ignore[reportMissingTypeStubs]
    install_run as core_install_run,
)
from vaultspec_core.core.enums import (  # pyright: ignore[reportMissingTypeStubs]
    InstallMode,
)
from vaultspec_core.core.exceptions import (  # pyright: ignore[reportMissingTypeStubs]
    VaultSpecError,
)
from vaultspec_core.core.manifest import (  # pyright: ignore[reportMissingTypeStubs]
    read_manifest,
    write_manifest,
)
from vaultspec_core.core.mcps import (  # pyright: ignore[reportMissingTypeStubs]
    render_mcp_definition_for_mode,
)
from vaultspec_core.core.workspace_mode import (  # pyright: ignore[reportMissingTypeStubs]
    PackageDeclaration,
    dependency_leak_advisory,
    read_package_declaration,
    write_package_declaration,
)

from ..builtins import seed_builtins
from ..commands import install_run
from ..commands._mode import (
    RAG_DISTRIBUTION_NAME,
    RAG_MCP_MODULE,
    infer_rag_upgrade_mode,
)
from ..config import EnvVar, persist_local_only, read_persisted_local_only, reset_config

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = [pytest.mark.unit]

#: The leak advisory rag emits names rag's own distribution, not core's, so the
#: text is package-correct on a companion install (install-parity W02.P07).
_RAG_LEAK_ADVISORY = dependency_leak_advisory(RAG_DISTRIBUTION_NAME)

# The concrete launch shapes each rendered mode produces for rag, derived from
# the install-parity ADR's Implementation section: dependency-rendered modes
# launch the module through the governed project's own venv (``uv run``), tool
# mode through an ephemeral ``uvx --from`` invocation. ``dev`` renders
# byte-identically to ``dependency``.
_DEP_LAUNCH = ("uv", ["run", "python", "-m", RAG_MCP_MODULE])
_TOOL_LAUNCH = (
    "uvx",
    ["--from", f"{RAG_DISTRIBUTION_NAME}[mcp]", "python", "-m", RAG_MCP_MODULE],
)

_PROJECT_WITH_RAG = (
    "[project]\n"
    'name = "demo-consumer"\n'
    'version = "0.1.0"\n'
    'dependencies = ["vaultspec-rag"]\n'
)
_PROJECT_RAG_DEV_GROUP = (
    "[project]\n"
    'name = "demo-consumer"\n'
    'version = "0.1.0"\n\n'
    "[dependency-groups]\n"
    'dev = ["vaultspec-rag"]\n'
)
_PROJECT_BARE = '[project]\nname = "demo-consumer"\nversion = "0.1.0"\n'


@pytest.fixture(autouse=True)
def _reset_config_around_each_test() -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]
    reset_config()
    yield
    reset_config()


def _workspace(tmp_path: Path, pyproject: str | None) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    if pyproject is not None:
        (ws / "pyproject.toml").write_text(pyproject, encoding="utf-8", newline="")
    return ws


def _install(ws: Path, *, mode: InstallMode | None = None, upgrade: bool = False):
    """Run a network-free rag install with the canonical MCP source enabled."""
    if not read_manifest(ws):
        write_manifest(ws, {"claude"})
    return install_run(
        path=ws,
        mode=mode,
        upgrade=upgrade,
        provision=False,
        configure_torch=False,
        install_mcp=True,
    )


def _rag_mcp_entry(ws: Path) -> dict[str, object]:
    raw = json.loads((ws / ".mcp.json").read_text(encoding="utf-8"))
    entry = raw["mcpServers"][RAG_DISTRIBUTION_NAME]
    assert isinstance(entry, dict)
    return cast("dict[str, object]", entry)


@pytest.mark.parametrize(
    ("explicit", "expected_command", "expected_args"),
    [
        (InstallMode.TOOL, _TOOL_LAUNCH[0], _TOOL_LAUNCH[1]),
        (InstallMode.DEPENDENCY, _DEP_LAUNCH[0], _DEP_LAUNCH[1]),
        (InstallMode.DEV, _DEP_LAUNCH[0], _DEP_LAUNCH[1]),
    ],
)
def test_explicit_mode_persists_and_renders_rag_entry(
    tmp_path: Path,
    explicit: InstallMode,
    expected_command: str,
    expected_args: list[str],
) -> None:
    """Each explicit mode persists rag's own entry and renders its own launch."""
    ws = _workspace(tmp_path, _PROJECT_WITH_RAG)

    _install(ws, mode=explicit)

    decl = read_package_declaration(ws, RAG_DISTRIBUTION_NAME)
    assert decl is not None
    assert decl.install_mode is explicit

    entry = _rag_mcp_entry(ws)
    assert entry["command"] == expected_command
    assert entry["args"] == expected_args


def test_detection_maps_rag_project_dependency_to_dependency_mode(
    tmp_path: Path,
) -> None:
    """A rag runtime dependency with no flag resolves to dependency mode."""
    ws = _workspace(tmp_path, _PROJECT_WITH_RAG)

    _install(ws)

    decl = read_package_declaration(ws, RAG_DISTRIBUTION_NAME)
    assert decl is not None
    assert decl.install_mode is InstallMode.DEPENDENCY
    assert _rag_mcp_entry(ws)["command"] == _DEP_LAUNCH[0]


def test_detection_maps_rag_dev_group_to_dev_mode(tmp_path: Path) -> None:
    """Rag in the default dev group with no flag resolves to the dev mode."""
    ws = _workspace(tmp_path, _PROJECT_RAG_DEV_GROUP)

    _install(ws)

    decl = read_package_declaration(ws, RAG_DISTRIBUTION_NAME)
    assert decl is not None
    assert decl.install_mode is InstallMode.DEV
    # Dev renders byte-identically to dependency.
    assert _rag_mcp_entry(ws)["command"] == _DEP_LAUNCH[0]


def test_no_pyproject_defaults_to_tool_mode(tmp_path: Path) -> None:
    """With no pyproject and no flag, rag falls through to the tool default."""
    ws = _workspace(tmp_path, None)

    _install(ws)

    decl = read_package_declaration(ws, RAG_DISTRIBUTION_NAME)
    assert decl is not None
    assert decl.install_mode is InstallMode.TOOL
    entry = _rag_mcp_entry(ws)
    assert entry["command"] == _TOOL_LAUNCH[0]
    assert entry["args"] == _TOOL_LAUNCH[1]


def test_explicit_dependency_without_pyproject_refuses(tmp_path: Path) -> None:
    """Dependency mode with nothing to declare against is a loud refusal."""
    ws = _workspace(tmp_path, None)

    with pytest.raises(VaultSpecError):
        _install(ws, mode=InstallMode.DEPENDENCY)


def test_mixed_configuration_preserves_sibling_and_renders_each_mode(
    tmp_path: Path,
) -> None:
    """Core dependency + rag tool: both entries kept, each at its own mode."""
    ws = _workspace(
        tmp_path,
        "[project]\n"
        'name = "demo-consumer"\n'
        'version = "0.1.0"\n'
        'dependencies = ["vaultspec-core", "vaultspec-rag"]\n',
    )

    core_install_run(path=ws, provider="all", mode=InstallMode.DEPENDENCY)
    _install(ws, mode=InstallMode.TOOL)

    core_decl = read_package_declaration(ws, "vaultspec-core")
    rag_decl = read_package_declaration(ws, RAG_DISTRIBUTION_NAME)
    assert core_decl is not None and core_decl.install_mode is InstallMode.DEPENDENCY
    assert rag_decl is not None and rag_decl.install_mode is InstallMode.TOOL

    servers = json.loads((ws / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]
    # Core keeps its dependency shape; rag renders its own tool shape.
    assert servers["vaultspec-core"]["command"] == "uv"
    assert servers[RAG_DISTRIBUTION_NAME]["command"] == _TOOL_LAUNCH[0]
    assert servers[RAG_DISTRIBUTION_NAME]["args"] == _TOOL_LAUNCH[1]


def test_rag_install_preserves_existing_core_declaration(tmp_path: Path) -> None:
    """Persisting rag's entry never clobbers a sibling core declaration."""
    ws = _workspace(tmp_path, _PROJECT_WITH_RAG)
    write_package_declaration(
        ws, "vaultspec-core", PackageDeclaration(install_mode=InstallMode.DEV)
    )

    _install(ws, mode=InstallMode.TOOL)

    core_decl = read_package_declaration(ws, "vaultspec-core")
    rag_decl = read_package_declaration(ws, RAG_DISTRIBUTION_NAME)
    assert core_decl is not None and core_decl.install_mode is InstallMode.DEV
    assert rag_decl is not None and rag_decl.install_mode is InstallMode.TOOL


def test_upgrade_keeps_persisted_mode_when_no_flag(tmp_path: Path) -> None:
    """A second upgrade with no flag is idempotent on the persisted mode."""
    ws = _workspace(tmp_path, _PROJECT_WITH_RAG)
    _install(ws, mode=InstallMode.TOOL)

    _install(ws, upgrade=True)

    decl = read_package_declaration(ws, RAG_DISTRIBUTION_NAME)
    assert decl is not None
    assert decl.install_mode is InstallMode.TOOL
    assert _rag_mcp_entry(ws)["command"] == _TOOL_LAUNCH[0]


def test_upgrade_flipping_rag_mode_migrates_managed_entry_without_force(
    tmp_path: Path,
) -> None:
    """A non-forced upgrade that flips rag's mode re-shapes its managed entry.

    The force-managed seam: a plain sync's force-gate would skip the already
    managed rag ``.mcp.json`` entry still carrying the old tool launch, leaving
    the deployed shape stale. The flip-detected migration must overwrite just
    rag's own entry into the new dependency shape.
    """
    ws = _workspace(tmp_path, _PROJECT_WITH_RAG)
    _install(ws, mode=InstallMode.TOOL)
    assert _rag_mcp_entry(ws)["command"] == _TOOL_LAUNCH[0]

    _install(ws, mode=InstallMode.DEPENDENCY, upgrade=True)

    decl = read_package_declaration(ws, RAG_DISTRIBUTION_NAME)
    assert decl is not None
    assert decl.install_mode is InstallMode.DEPENDENCY
    entry = _rag_mcp_entry(ws)
    assert entry["command"] == _DEP_LAUNCH[0]
    assert entry["args"] == _DEP_LAUNCH[1]


def test_infer_upgrade_mode_explicit_wins(tmp_path: Path) -> None:
    """An explicit flag on upgrade outranks any deployed evidence."""
    ws = _workspace(tmp_path, _PROJECT_WITH_RAG)

    resolved = infer_rag_upgrade_mode(ws, InstallMode.TOOL)

    assert resolved.mode is InstallMode.TOOL


def test_infer_upgrade_mode_persisted_wins(tmp_path: Path) -> None:
    """A persisted rag declaration outranks detection on upgrade."""
    ws = _workspace(tmp_path, _PROJECT_WITH_RAG)
    write_package_declaration(
        ws, RAG_DISTRIBUTION_NAME, PackageDeclaration(install_mode=InstallMode.TOOL)
    )

    resolved = infer_rag_upgrade_mode(ws, None)

    # Persisted tool wins over the dependency the pyproject would detect.
    assert resolved.mode is InstallMode.TOOL


def test_infer_upgrade_mode_legacy_dependency_shape(tmp_path: Path) -> None:
    """A legacy dependency-shaped deployment with no declaration infers dependency."""
    ws = _workspace(tmp_path, _PROJECT_WITH_RAG)
    seed_builtins(ws / ".vaultspec", force=True)
    # Deployed dependency-mode MCP launch, no committed declaration - the legacy
    # state install --upgrade must recognize.
    mcp = {
        "_vaultspecManaged": [RAG_DISTRIBUTION_NAME],
        "mcpServers": {
            RAG_DISTRIBUTION_NAME: {
                "command": _DEP_LAUNCH[0],
                "args": list(_DEP_LAUNCH[1]),
            }
        },
    }
    (ws / ".mcp.json").write_text(json.dumps(mcp), encoding="utf-8")

    resolved = infer_rag_upgrade_mode(ws, None)

    assert resolved.mode is InstallMode.DEPENDENCY


def test_infer_upgrade_mode_legacy_tool_shape(tmp_path: Path) -> None:
    """A legacy tool-shaped deployment with no declaration infers tool mode."""
    ws = _workspace(tmp_path, _PROJECT_BARE)
    mcp = {
        "mcpServers": {
            RAG_DISTRIBUTION_NAME: {
                "command": _TOOL_LAUNCH[0],
                "args": list(_TOOL_LAUNCH[1]),
            }
        }
    }
    (ws / ".mcp.json").write_text(json.dumps(mcp), encoding="utf-8")

    resolved = infer_rag_upgrade_mode(ws, None)

    assert resolved.mode is InstallMode.TOOL


@pytest.mark.parametrize(
    ("mode", "expected_command", "expected_args"),
    [
        (InstallMode.TOOL, _TOOL_LAUNCH[0], _TOOL_LAUNCH[1]),
        (InstallMode.DEPENDENCY, _DEP_LAUNCH[0], _DEP_LAUNCH[1]),
        (InstallMode.DEV, _DEP_LAUNCH[0], _DEP_LAUNCH[1]),
    ],
)
def test_tokenized_builtin_renders_expected_launch(
    mode: InstallMode, expected_command: str, expected_args: list[str]
) -> None:
    """The shipped tokenized builtin renders the right launch through core."""
    builtin = files("vaultspec_rag.builtins") / "mcps" / "vaultspec-rag.builtin.json"
    definition = json.loads(builtin.read_text(encoding="utf-8"))

    rendered = render_mcp_definition_for_mode(definition, mode)

    assert rendered["command"] == expected_command
    assert rendered["args"] == expected_args
    # Substitution-metadata keys never reach a rendered definition.
    assert "_vaultspec_mode_package" not in rendered
    assert "_vaultspec_mode_module" not in rendered


def test_advisory_fires_when_run_newly_elects_dependency(tmp_path: Path) -> None:
    """A fresh dependency-mode election surfaces the leak advisory."""
    ws = _workspace(tmp_path, _PROJECT_WITH_RAG)

    report = _install(ws, mode=InstallMode.DEPENDENCY)

    assert _RAG_LEAK_ADVISORY in report.warnings
    # The advisory names rag, not core, on a companion dependency election.
    assert RAG_DISTRIBUTION_NAME in _RAG_LEAK_ADVISORY


def test_advisory_silent_on_persisted_dependency_read(tmp_path: Path) -> None:
    """A persisted dependency declaration is not re-nagged on the next run."""
    ws = _workspace(tmp_path, _PROJECT_WITH_RAG)
    _install(ws, mode=InstallMode.DEPENDENCY)

    report = _install(ws)

    assert _RAG_LEAK_ADVISORY not in report.warnings


def test_advisory_silent_for_tool_mode(tmp_path: Path) -> None:
    """Tool mode never leaks downstream, so it never fires the advisory."""
    ws = _workspace(tmp_path, _PROJECT_WITH_RAG)

    report = _install(ws, mode=InstallMode.TOOL)

    assert _RAG_LEAK_ADVISORY not in report.warnings


def test_local_only_marker_is_orthogonal_to_mode_declaration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The per-host local-only backend marker never folds into the mode map."""
    status_dir = tmp_path / "managed"
    monkeypatch.setenv(EnvVar.STATUS_DIR.value, str(status_dir))
    reset_config()
    ws = _workspace(tmp_path, _PROJECT_WITH_RAG)

    # A mode install (local_only is inert without provisioning) must still leave
    # the shared declaration carrying only the mode axis, never a backend field.
    _install(ws, mode=InstallMode.TOOL)

    raw = json.loads((ws / ".vaultspec" / "workspace.json").read_text(encoding="utf-8"))
    entry = raw["packages"][RAG_DISTRIBUTION_NAME]
    assert set(entry).issubset({"install_mode", "minimum_version"})
    assert "local_only" not in entry

    # The backend selection lives in its own per-host marker, disjoint from the
    # committed workspace declaration.
    marker = persist_local_only(True)
    assert read_persisted_local_only() is True
    assert marker != ws / ".vaultspec" / "workspace.json"
    assert not marker.is_relative_to(ws)
