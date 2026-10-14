---
tags:
  - '#adr'
  - '#provider-mcp-enrollment'
date: '2026-07-15'
modified: '2026-10-14'
body_hash: 'sha256:165f32cec9c52c9d00dbda7cb39f43844f79b7cdfb29a8fec6939e9656edd266'
related:
  - "[[2026-07-15-provider-mcp-enrollment-research]]"
  - '[[2026-07-15-provider-mcp-enrollment-audit]]'
---

# `provider-mcp-enrollment` adr: `Core-managed provider lifecycle with RAG-owned enrollment intent and placement` | (**status:** `accepted`)

## Problem Statement

RAG exposes an optional MCP server to multiple agent hosts whose project
configuration contracts differ. Claude Code consumes project entries from shared JSON,
while Codex consumes native TOML. RAG currently delegates only a JSON projection to
Core, installs the MCP extra without respecting tool, dependency, or dev placement, and
treats `--no-mcp` as a dependency opt-out while still enrolling the server.

The architecture must assign one owner to provider configuration, preserve project
scope and user ownership, and keep MCP dependency placement consistent with RAG's three
installation modes.

## Considerations

- Core is already the workspace's provider-integration authority and RAG's canonical
  sync delegate.
- RAG alone knows whether the operator requested MCP enrollment and where its optional
  dependency belongs.
- Claude and Codex require different project-native schemas; a healthy target for one
  provider says nothing about the other.
- Tool mode must not mutate the governed project's dependencies, and dev mode must not
  promote RAG into published runtime requirements.
- Same-name host entries without Vaultspec ownership are user-owned collisions.
- A CLI-only installation must not leave a configured but unlaunchable server.
- Install, upgrade, dry-run, status, migration, and uninstall need one ownership and
  drift model.
- Active Codex sessions may require restart, and Claude project entries may require
  approval, after configuration becomes healthy.

## Considered options

- **Delegate project-native lifecycle to Core while RAG owns intent and dependency
  placement - chosen.** One canonical RAG definition is projected through Core's typed
  provider targets; RAG decides whether enrollment exists and applies the MCP extra only
  at the resolved package surface.
- **Let RAG write Claude JSON and Codex TOML directly - rejected.** This duplicates
  provider schemas, ownership tracking, merge safety, drift detection, and uninstall
  behavior already owned by Core.
- **Register servers through host CLIs - rejected.** Host commands have inconsistent
  scope controls, tend toward user-global configuration, and make repository enrollment
  non-portable.
- **Continue treating `.mcp.json` as universal - rejected.** It enrolls Claude Code but
  does not establish Codex enrollment.
- **Keep unconditional `uv add vaultspec-rag[mcp]` - rejected.** It mutates tool-mode
  projects and can move a dev-only dependency into published runtime requirements.
- **Automatically adopt every same-name host entry - rejected.** Name equality is not
  evidence of Vaultspec ownership.
- **Ship separate RAG definitions per provider - rejected.** Multiple declarations
  create independent launch contracts that can drift.

## Constraints

- RAG uses Core's public `McpScope`, `McpTarget`, `mcp_sync`, `mcp_status`, and
  `mcp_uninstall` contracts. It does not introduce provider serializers or a second MCP
  ownership registry.
- Core distinguishes RAG's package identity, `vaultspec-rag`, from its tool-mode
  distribution spec, `vaultspec-rag[mcp]`.
- Only `McpScope.PROJECT` participates in RAG's default lifecycle. User-global host
  configuration is out of scope.
- Core's provider contract is accepted but not yet published. RAG cannot release this
  feature until the artifact exists and passes cross-provider acceptance.
- Existing Core-owned JSON entries may be migrated. Existing unowned Codex tables stay
  user-owned unless an explicit force operation authorizes replacement.
- RAG lacks trustworthy provenance for dependency-extra changes made by older releases.
  Migration must not guess that a historical runtime requirement is safe to remove.
- New dependency-extra changes record their placement so reversal removes only the
  managed `[mcp]` addition and retains the base dependency.
- Dry-run executes the real Core planning path but writes no files, runs no dependency
  mutation, and performs no external provisioning.
- Repeated install or upgrade with identical inputs is byte-stable and avoids needless
  dependency resolution.
- Tests use real temporary workspaces and real CLIs; no mocks, fakes, patches, skips, or
  mirrored business logic.
- Amendment, 2026-10-14. Core enrolls a launch only after the operator has reviewed its
  exact definition and launch and approved it in a record kept outside the workspace; its
  own install grants nothing, and no flag stands in for that review. RAG's install
  therefore asks the operator to approve RAG's own definition, and only that one, at an
  attended terminal, and records the answer through Core's public grant. An unattended
  run, or `--yes`, never asks and never grants: the sync skips the launch with Core's
  message naming the command that grants it. A dry run never writes. A sibling definition
  stays the operator's to approve with Core. The approval is the operator's decision about
  that exact launch, so it outlives an install that fails and rolls back. Authorization:
  the user's 2026-10-14 instruction to fix the install gaps ("fix all") authorizes this
  refinement. It adds an operator step to enrollment and does not change which component
  owns provider configuration.
- Core binds approval to where a definition really lives. An install holds a linked
  definition or native config as a regular copy until it commits, and Core asks about that
  copy's path while the install syncs. The approval is therefore recorded at the real
  location first, which every later sync of the workspace asks about, and an approval
  already held at the real location is recorded at the copy's path for the run. That
  second record is the same reviewed launch, made only for a launch already approved at
  its real location. It creates no consent and matches nothing once the link is back.

## Implementation

RAG will continue shipping one mode-neutral MCP definition. The definition identifies
`vaultspec-rag` as the declaring package and separately declares
`vaultspec-rag[mcp]` as the tool-mode distribution specification. Core projects this
source to Claude project JSON and Codex project TOML while preserving unrelated and
user-owned provider configuration.

RAG owns the enrollment switch. `--mcp` retains the MCP source and requests Core
synchronization. `--no-mcp` retains RAG's rule and discovery skill, removes or omits the
MCP source, and asks Core to prune only RAG's managed provider projections.

Dependency placement follows the resolved mode:

| Mode         | Managed dependency action                         | Rendered launch                                                |
| :----------- | :------------------------------------------------ | :------------------------------------------------------------- |
| `tool`       | No project dependency mutation                    | `uvx --from vaultspec-rag[mcp] python -m vaultspec_rag.server` |
| `dependency` | Add `[mcp]` to the existing runtime requirement   | `uv run python -m vaultspec_rag.server`                        |
| `dev`        | Add `[mcp]` to the existing dev-group requirement | `uv run python -m vaultspec_rag.server`                        |

Newly managed dependency changes carry location provenance in RAG-owned workspace
state. Legacy placement without provenance is reported rather than silently corrected.
Install, upgrade, mode migration, dry-run, and uninstall pass provider work through
Core's typed lifecycle, and structured RAG reports retain Core's per-target results.

Install plans the launches it will enroll from the projection a dry run uses, before
any write and before the replay that journals rollback state, so the replay and the real
run agree on what is approved. It shows the operator the exact definition, digest, launch
and target of RAG's own definition, asks once, and records the answer with Core's grant.
An approval Core already holds for the same definition and launch is reused without a
question, and a changed definition or launch is asked about again.
Once the install has swapped its links for regular copies, it carries that approval to
the copies' paths, so the install's own sync is not refused for a launch the operator
approved.

A managed mode transition uses the narrow `force_managed` path. An unowned same-name
entry produces a collision and remains unchanged unless the operator explicitly forces
adoption. Dry-run computes dependency placement and calls Core's provider-aware dry-run
without invoking `uv add`.

RAG's dependency floor rises to the first published Core version carrying the typed
provider lifecycle and extra-aware tool renderer. The RAG release resolves against that
published artifact, not a local checkout.

## Rationale

Core knows how each host represents project-scoped MCP servers and already owns provider
merge, preservation, drift, and uninstall semantics. RAG knows whether its optional
surface should exist and which dependency surface corresponds to its installation mode.

Keeping those responsibilities separate prevents schema duplication without making
Core responsible for RAG's packaging policy. One canonical definition keeps Claude and
Codex on the same server launch, while the distinct tool distribution specification
makes the optional dependency available without corrupting package-mode identity.

Project scope keeps enrollment repository-local and reproducible. Explicit ownership
prevents upgrades from converting user configuration into managed state merely because
names match. Placement provenance restores symmetric reversal for future changes while
honestly refusing to infer ownership that older releases never recorded.

## Consequences

- Claude Code and Codex receive native project-scoped enrollment from one canonical RAG
  declaration.
- Provider health becomes conjunctive across selected targets.
- Tool installs stop mutating project dependencies, and dev installs stop leaking RAG
  into published runtime requirements.
- `--no-mcp` becomes a genuine CLI-only state.
- Install, upgrade, dry-run, status, migration, and uninstall share Core's ownership and
  drift semantics.
- RAG acquires a hard release dependency on the forthcoming Core version and cannot ship
  independently of it.
- Dependency-placement provenance adds persistent state and migration logic.
- Legacy dependency leakage cannot always be repaired automatically; some users receive
  an explicit manual migration.
- Provider activation remains host-specific: Claude may require approval and an active
  Codex session may require restart.
- Adding another provider becomes a Core `McpTarget` concern instead of a new RAG
  serializer.
- An unattended install, or one run with `--yes`, completes without enrolling the server
  until the operator grants approval with Core, then installs again.

## Codification candidates

- **Rule slug:** `companion-provider-config-has-one-writer`
  **Rule:** A companion package declares enrollment intent and canonical source data,
  but only the provider authority renders, merges, diagnoses, and removes host-native
  project configuration.
- **Rule slug:** `optional-surface-dependency-follows-install-mode`
  **Rule:** Enabling an optional runtime surface places its dependency at the resolved
  installation surface: no project mutation for tool mode, runtime placement for
  dependency mode, and unpublished group placement for dev mode.
- **Rule slug:** `same-name-host-entry-is-not-ownership`
  **Rule:** A provider entry is managed only through explicit durable provenance;
  matching a canonical server name never authorizes adoption, overwrite, drift repair,
  or removal.
