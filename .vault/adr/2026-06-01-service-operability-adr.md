---
tags:
  - '#adr'
  - '#service-operability'
date: '2026-06-01'
modified: '2026-06-01'
related:
  - "[[2026-06-01-service-operability-research]]"
  - "[[2026-05-28-cli-backend-parity-adr]]"
  - "[[2026-04-12-store-eviction-log-rotation-adr]]"
  - "[[2026-04-02-service-graph-adr]]"
  - "[[2026-05-30-service-lifecycle-adr]]"
  - "[[2026-05-30-cli-json-output-adr]]"
---

# `service-operability` adr: auto-reindex + watcher control — CLI/MCP parity contract | (**status:** `accepted`)

## Problem Statement

The resident RAG service already auto-reindexes on file change via a filesystem
watcher, but the capability is an emergent side-effect rather than a designed
feature: watcher tuning is hardcoded (`debounce` 2000 ms, per-source `cooldown`
30 s), the watcher starts lazily and implicitly on the first search/reindex
tool call per project root, there is no way to disable it, no CLI flag or env
var configures it, and nothing documents that it exists. This surfaced in
production — a single resident service shared by multiple concurrent agents
against one worktree — where operators could neither tune, disable, nor control
the watcher from the CLI.

The deeper, governing problem is a parity gap: **the CLI cannot control the
running server on par with MCP.** This ADR is ADR-A of the `service-operability`
cluster and folds GitHub issues #143 (watcher/auto-reindex configurability) and
#144 (auto-reindex as a first-class, opt-out-able feature). It decides the
auto-reindex/watcher **configuration and control** contract under a governing
CLI ⇄ MCP parity principle. The observability/state surface (#142 — logs, jobs,
status, projects, metrics) is deliberately deferred to ADR-B; this ADR exposes
only the minimal watcher-state read needed for control feedback.

A fourth issue, #145, tracks hardening the *shipped built-in rule* into an
imperative DO/DO NOT usage mandate, revisited as each feature in the cluster
lands. It intersects this ADR in two binding ways: #144 **inverts** an existing
directive (the rule currently tells agents to reindex manually — once the
service auto-reindexes, the directive must become "DO NOT manually reindex;
DO use `--no-watch` for pull-only"), and #145 asks for a maintenance guard so a
behaviour change cannot ship without the matching directive update. This ADR
therefore owns the directive corrections its own behaviour change forces, plus
that guard; the broader imperative restructure of the rule (the resident-service
single-writer mandate, RAG-vs-grep selection) is left to #145 as a consolidated
documentation-workflow pass after #142, to avoid rewriting the rule twice.

## Considerations

- **Governing decision — full bidirectional CLI ⇄ MCP parity over the
  server-runtime surface.** Every watcher/auto-reindex capability must be
  reachable and controllable from *both* the CLI and MCP. This extends the
  established `cli-backend-parity` contract (previously scoped to search
  capabilities) to the service-runtime/control surface. The framing the issues
  used ("expose MCP/HTTP surfaces") is a symptom; parity is the decision.
- **Control already rides MCP, not a second transport.** The CLI reaches the
  running daemon today as an MCP client through the `_try_mcp_admin(tool, args, port)` seam (used by `service projects list/evict`). New control verbs extend
  that seam — they do not add a parallel HTTP control API.
- **The config layer has a clean, type-coercing extension point.** New settings
  are a three-point change: a default in `_RAG_DEFAULTS`, an `EnvVar` member,
  and an `_ENV_OVERRIDE_MAP` entry; bool/int/float coercion from env is already
  driven by the default's type. Precedence is explicit value → env → default.
- **The watcher params already exist but are never wired.** `watch_and_reindex`
  accepts `debounce`/`cooldown`; `_ensure_watcher` calls it without them, so the
  literals always win. Threading config-derived values in is the whole backend
  change.
- **Prior decisions to honour.** No second HTTP control transport (the admin
  route was rejected); the `{ok, command, data}` / `{ok, error, message}` JSON
  envelope and stable exit codes (0 running / 3 stopped / 4 divergent / 2 usage);
  no background sweeper/timer thread; global-only config for beta (per-project
  overrides deferred previously).

## Constraints

- **The daemon inherits only environment, not argv.** `service start` launches a
  detached subprocess that parses no arguments beyond `--port`. Therefore CLI
  startup flags cannot reach the daemon directly; they must be translated into
  `VAULTSPEC_RAG_WATCH*` environment variables on the child env dict before the
  process is spawned. The env is the real source of truth; the flags are sugar
  over it.
- **`awatch` debounce is fixed at construction.** The underlying watch loop sets
  its debounce when it is created, so a running watcher cannot have its debounce
  mutated in place. Runtime reconfiguration is therefore defined as **stop +
  restart** of the affected root's watcher with the new values — not an in-place
  update.
- **The service is multi-project; roots are unknown at startup.** A freshly
  started service holds no project until the first request leases one. A *global*
  "eager start at `service start`" is thus a non-sequitur — there is nothing to
  watch yet. Eager start only has meaning per-root, once a root is known.
- **Parent-feature stability.** This ADR depends only on shipped, stable
  surfaces: the config wrapper, the `_try_mcp_admin` CLI-as-MCP-client seam, the
  `watch_and_reindex` signature, and the service lifecycle/heartbeat. No frontier
  or immature dependency; no new third-party library.

## Implementation

A high-level layering of *what* changes; the concrete call sites and signatures
belong in the plan/reference, not here.

- **Config keys (backend).** Add three settings via the three-point pattern:
  `watch_enabled` (bool, default `true`), `watch_debounce_ms` (int, default
  `2000`), `watch_cooldown_s` (float, default `30.0`). Disabling the watcher is
  done **solely** through `watch_enabled`; a `0` for debounce or cooldown means
  "no delay", *not* "disabled" — the enable flag and the tuning knobs are
  orthogonal so neither overloads the other's meaning.
- **Startup CLI surface.** `service start` gains `--watch/--no-watch`,
  `--watch-debounce-ms`, and `--watch-cooldown-s`. Each is translated to its
  `VAULTSPEC_RAG_WATCH*` env var on the child env before spawn; flags left at
  their default (detected via the Typer parameter source) do not clobber an env
  value already set by the operator. Include/exclude glob flags are **deferred**
  (the watcher's watched set is fixed today; globbing is its own design).
- **Runtime control parity.** Add MCP tools — `start_watcher`, `stop_watcher`,
  `reconfigure_watcher`, and a minimal `get_watcher_state` — and matching CLI
  subcommands under a `server watcher` group (`start`, `stop`, `status`,
  `reconfigure`) that drive the running daemon through the existing
  `_try_mcp_admin` seam. Control rides MCP; no HTTP control route is added.
  `reconfigure` is stop-then-restart of the named root's watcher with new
  values.
- **Lifecycle decision.** Lazy-per-root start remains the default mechanism —
  correct for a multi-project service — but it is now **gated by
  `watch_enabled`**: when disabled, no watcher starts and the service is
  pull-only (manual/scheduled indexing). Eager activation is available
  explicitly and per-root via `watcher start <root>`. Global eager-at-startup is
  rejected (see Constraints).
- **Plumbing.** The chain is: CLI flag → `VAULTSPEC_RAG_WATCH*` env (set in the
  spawn path) → `get_config()` → the `_ensure_watcher` call sites (guarded by
  `watch_enabled`) → `watch_and_reindex(debounce=…, cooldown=…)`. The watcher
  function already accepts the params; this ADR wires config-derived values into
  the call and adds the enable guard.
- **Scope boundary.** Only `get_watcher_state` (the control-feedback read) is in
  scope here; the rich state/observability surface (logs, jobs/queue, status,
  projects, metrics) is ADR-B and consumes the same watcher state this exposes.

## Rationale

The research grounded every issue claim against current source and found the
backend already 80% capable: the watcher accepts tuning params, the config layer
has a coercing extension point, and the CLI already controls the daemon over
MCP. The missing piece is not a new transport — it is *wiring and parity*. Making
parity the explicit decision (rather than "add HTTP endpoints") is what keeps the
prior admin-route rejection intact: the CLI gains control by extending the MCP
client seam, not by standing up a competing control plane. Choosing
`watch_enabled` as the sole disable lever (and treating `0` as "no delay")
follows the research's open-question analysis and avoids the sentinel-overloading
trap. Defining runtime reconfigure as stop+restart is forced by the constraint
that `awatch` fixes debounce at construction. Keeping lazy-per-root as default
respects the multi-project model the service-graph work established, while the
explicit per-root eager control and the global opt-out satisfy #144's
first-class/opt-out requirements without inventing a meaningless global eager
start.

## Consequences

- **Gains.** Operators can disable auto-reindex for a pull-only workflow, tune
  debounce/cooldown to their corpus, and start/stop/reconfigure/inspect the
  watcher on the running daemon from either the CLI or MCP. Auto-reindex becomes
  discoverable and documented instead of folkloric.
- **Honest difficulties.** Reconfigure-as-restart momentarily drops the affected
  root's debounce window and re-arms its cooldown — acceptable, but a real
  behavioural seam to test. Because the daemon is env-only, the CLI startup flags
  are genuinely just sugar over `VAULTSPEC_RAG_WATCH*`; the docs must name the
  env vars as the canonical surface so headless/containerized operators are not
  misled into thinking the flags reach an already-running daemon. Per-project
  config remains deferred; runtime `reconfigure <root>` only partially
  compensates (it does not persist across restart).
- **Pitfalls.** Bool env coercion must accept the documented truthy/falsey set
  consistently; the new `server watcher` subcommands must observe the established
  JSON-envelope + exit-code contract and the no-silent-swallow rule on every
  `_try_mcp_admin` branch; and the `watch_enabled` guard must not regress the
  lazy-start behaviour existing tests rely on.
- **Pathways opened.** The `get_watcher_state` read and the in-flight signal it
  needs feed directly into ADR-B's state surface; the parity precedent set here
  is the template ADR-B reuses for logs/jobs/status/projects.
- **Docs (consequence, not a decision).** Per the parity contract, the new
  config and control surface is documented in three places — the top-level
  `README.md`, the package `README.md`, and the `vaultspec-rag.builtin.md` rule.
  Per #145, the builtin-rule change is **not** a prose append but an imperative
  DO/DO NOT directive edit: the obsolete "manually reindex" directive is
  inverted to "DO NOT manually reindex during normal work; DO use `--no-watch`
  for pull-only", and the new watcher knobs are stated as directives. A
  maintenance check (a test asserting the builtin rule carries the required
  auto-reindex/opt-out directive tokens) guards against the rule drifting behind
  shipped behaviour. The full imperative restructure of the rule remains tracked
  by #145.

## Codification candidates

- **Rule slug:** `cli-mcp-control-parity`.
  **Rule:** Every server-runtime capability — control or observation — exposed
  on one of the CLI or MCP must be exposed on the other, with the CLI reaching
  the running daemon through the MCP client seam rather than a parallel
  transport.
- **Rule slug:** `service-behaviour-updates-builtin-directives`.
  **Rule:** Any change to resident-service behaviour must update the shipped
  built-in rule's DO/DO NOT directive set in the same change, enforced by a
  maintenance check (origin: #145).

## Deferred / rejected alternatives

- **Service-managed periodic full rebuild (#144 item 4) — DEFERRED, default
  off.** A configurable interval that triggers a full `--rebuild` to defeat
  incremental drift was considered and is **carved out of this ADR.** It
  reintroduces exactly the background-timer/sweeper pattern repeatedly rejected
  for project eviction (eviction was kept lazy/traffic-triggered precisely to
  avoid a standing background thread). Whether scheduled rebuild is exempt from
  that standing constraint is its own decision; it must not ride in on the
  watcher-config work. Recommended default if ever adopted: off.
- **Global eager watcher start at `service start` — REJECTED.** Meaningless for
  a multi-project service that holds no root until first request; superseded by
  per-root explicit `watcher start` plus the global `watch_enabled` opt-out.
- **A second HTTP control transport for watcher control — REJECTED.** Honours the
  prior admin-route rejection; control rides the existing MCP client seam.

## Open questions (to settle in the plan)

- Per-project vs global watcher config: global-only for now (consistent with the
  prior beta deferral); runtime `reconfigure <root>` gives per-root tuning
  without persistence.
- Exact `server watcher` subcommand/flag names, checked against existing CLI
  tokens to avoid collisions.
- Whether `reconfigure` on a not-yet-running root is a no-op, an error, or an
  implicit start.
