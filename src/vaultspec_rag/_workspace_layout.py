"""Where the vaultspec workspace keeps its files, relative to a project root.

The directory name was spelled thirty-one times across five modules, and the
names inside it fared no better - ``rules`` seven times, ``mcps`` six,
``mcp-ownership.json`` four. Nothing owned the layout, so installing it,
projecting it, uninstalling it and seeding a synthetic copy of it each carried
their own idea of what it contains.

Everything here is RELATIVE to a project root, because both shapes the callers
use need that: the topology module holds these as module constants and
compares them against paths it is given, while the install and workspace verbs
join them onto a target. A caller writes ``root / VAULTSPEC_MCPS`` and the
join reads the same either way.

Naming the workspace directory in code is deliberate and not a vault
reference: this package installs and removes that directory, so its layout is
product vocabulary the way ``.vault/`` markdown and ``adr/`` doc ids are.
"""

from __future__ import annotations

from pathlib import Path

__all__ = [
    "VAULTSPEC_DIR",
    "VAULTSPEC_MCPS",
    "VAULTSPEC_MCP_OWNERSHIP",
    "VAULTSPEC_PROVIDERS",
    "VAULTSPEC_RULES",
    "VAULTSPEC_SKILLS",
    "VAULTSPEC_WORKSPACE",
    "VAULT_DATA_DIR",
    "VAULT_DIR",
    "workspace_directories",
]

#: The vault corpus directory and the container the index lives beneath.
#: Distinct from ``config.data_dir``, which defaults to a path INSIDE this one
#: and is operator-overridable: these two are scaffolding the install creates
#: regardless of where the index is configured to land.
VAULT_DIR = Path(".vault")
VAULT_DATA_DIR = VAULT_DIR / "data"

#: The workspace directory itself.
VAULTSPEC_DIR = Path(".vaultspec")

#: The provider-source subdirectories a workspace is scaffolded with.
VAULTSPEC_RULES = VAULTSPEC_DIR / "rules"
VAULTSPEC_MCPS = VAULTSPEC_DIR / "mcps"
VAULTSPEC_SKILLS = VAULTSPEC_DIR / "skills"

#: The manifests the install and topology paths read and write.
VAULTSPEC_WORKSPACE = VAULTSPEC_DIR / "workspace.json"
VAULTSPEC_PROVIDERS = VAULTSPEC_DIR / "providers.json"
VAULTSPEC_MCP_OWNERSHIP = VAULTSPEC_DIR / "mcp-ownership.json"


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
        VAULTSPEC_DIR,
        VAULTSPEC_RULES,
        VAULTSPEC_MCPS,
        VAULTSPEC_SKILLS,
    )
