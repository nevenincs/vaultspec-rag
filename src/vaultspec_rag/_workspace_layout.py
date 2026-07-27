"""Where the vaultspec workspace keeps its files, relative to a project root.

The directory name was spelled thirty-one times across five modules, and the
names inside it fared no better - ``rules`` seven times, ``mcps`` six,
``mcp-ownership.json`` four. Nothing owned the layout, so installing it,
projecting it, uninstalling it and seeding a synthetic copy of it each carried
their own idea of what it contains.

Everything here is RELATIVE to a project root, because both shapes the callers
use need that: the topology module holds these as module constants and
compares them against paths it is given, while the install and workspace verbs
join them onto a target. A caller writes ``root / WORKSPACE_MCPS`` and the
join reads the same either way.

Naming the workspace directory in code is deliberate and not a vault
reference: this package installs and removes that directory, so its layout is
product vocabulary the way ``.vault/`` markdown and ``adr/`` doc ids are.
"""

from __future__ import annotations

from pathlib import Path

__all__ = [
    "MCP_OWNERSHIP_MANIFEST",
    "PROVIDERS_MANIFEST",
    "VAULT_DATA_DIR",
    "VAULT_DIR",
    "WORKSPACE_DIR",
    "WORKSPACE_MANIFEST",
    "WORKSPACE_MCPS",
    "WORKSPACE_RULES",
    "WORKSPACE_SKILLS",
    "workspace_directories",
]

#: The vault corpus directory and the container the index lives beneath.
#: Distinct from ``config.data_dir``, which defaults to a path INSIDE this one
#: and is operator-overridable: these two are scaffolding the install creates
#: regardless of where the index is configured to land.
VAULT_DIR = Path(".vault")
VAULT_DATA_DIR = VAULT_DIR / "data"

#: The workspace directory itself. Named WORKSPACE_ rather than VAULTSPEC_
#: because this codebase reserves the ``VAULTSPEC_`` identifier prefix for
#: environment-variable names, and a guard asserts every such literal is a
#: declared setting - which these paths are not.
WORKSPACE_DIR = Path(".vaultspec")

#: The provider-source subdirectories a workspace is scaffolded with.
WORKSPACE_RULES = WORKSPACE_DIR / "rules"
WORKSPACE_MCPS = WORKSPACE_DIR / "mcps"
WORKSPACE_SKILLS = WORKSPACE_DIR / "skills"

#: The manifests the install and topology paths read and write.
WORKSPACE_MANIFEST = WORKSPACE_DIR / "workspace.json"
PROVIDERS_MANIFEST = WORKSPACE_DIR / "providers.json"
MCP_OWNERSHIP_MANIFEST = WORKSPACE_DIR / "mcp-ownership.json"


def workspace_directories() -> tuple[Path, ...]:
    """Return every directory a scaffolded workspace contains, outermost first.

    Ordered so a caller creating them can walk the tuple, and so a caller
    removing them can walk it reversed without a directory outliving its
    parent.

    The scaffolder and the topology projection each listed these six for
    themselves. A directory added to one and not the other is how a projected
    workspace comes out missing a tree the real one has - which is precisely
    what the projection exists to be a faithful copy of.
    """
    return (
        VAULT_DIR,
        VAULT_DATA_DIR,
        WORKSPACE_DIR,
        WORKSPACE_RULES,
        WORKSPACE_MCPS,
        WORKSPACE_SKILLS,
    )
