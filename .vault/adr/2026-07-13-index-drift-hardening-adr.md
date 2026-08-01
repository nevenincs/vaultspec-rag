---
tags:
  - '#adr'
  - '#index-drift-hardening'
date: '2026-07-13'
modified: '2026-07-13'
body_hash: 'sha256:50a02bf50d7cceddbefdcf068a042be7019ed658b8e96fd9ab37484223915f84'
related:
  - '[[2026-07-13-index-drift-hardening-research]]'
  - '[[2026-04-04-vaultragignore-adr]]'
  - '[[2026-06-02-watcher-targeted-reindex-adr]]'
  - '[[2026-06-10-preprocess-hooks-adr]]'
  - '[[2026-06-19-destructive-ops-security-audit]]'
---

# `index-drift-hardening` adr: `config-epoch drift sentinel and preprocess TOFU default` | (**status:** `accepted`)

## Problem Statement

A rag consumer team surfaced two capability drifts. First, index-shaping configuration
is not tracked: chunks of files newly ignored via `.vaultragignore` linger in the
index indefinitely under the resident watcher, because the watcher only ever runs
scoped incremental reindex keyed off file byte hashes, and no signal records what
configuration the index was built against. Second, preprocess hooks are silently inert
unless a host-global, undocumented env flag is present in the service process env -
the capability is effectively invisible. The product decision is that preprocess must
work on by default without per-index client action, which requires reconciling the
untrusted-repo RCE finding (audit C1) that made it off by default. Derived from the
`index-drift-hardening` research.

## Considerations

- The scoped-reindex ADR deliberately made watcher work O(changed files); any drift
  check must not reintroduce per-run full-tree cost.
- The vaultragignore ADR D8 ("ignore edits take effect on the next index run
  naturally") was silently invalidated when watcher runs became scoped - this ADR
  restores its intent without reverting to full scans.
- The existing sentinels (`_needs_embed_rebuild`, `_needs_layout_rebuild`) are a
  proven precedent: reserved meta-sidecar key, checked at incremental entry under the
  writer lock, self-escalating.
- Unscoped incremental reconciles membership drift fully (set arithmetic over a fresh
  ignore-aware scan) but is blind to content-output drift on unchanged bytes; the two
  drift classes need different escalations.
- Audit C1 resolved preprocess RCE with a blanket off-by-default env gate; the
  audit's own recommendation included trust-on-first-use confirmation of the command
  set, which never shipped. Root registration (a search from a cloned repo) is not a
  defensible consent boundary.
- Control-surface parity precedent is `local_only`: config knob + env var + CLI flag
  forwarded into the daemon env.
- The preprocess config loader is imported by the CPU-only spawn chunk worker;
  anything added there must stay stdlib-light and torch-free.

## Considered options

- **O1: watcher watches scaffold files and forces unscoped runs.** Rejected: puts
  drift classification in an adapter (violates service-domain-owns-operability) and
  leaves explicit scoped CLI/MCP callers unguarded.
- **O2: periodic epoch check on watcher idle ticks.** Rejected: recurring cost on
  quiet trees, same scoped-caller gap.
- **O3: config epoch checked inside every incremental entry, self-escalating in the
  indexer.** Chosen: every entry point self-heals, zero watcher changes, reuses the
  sentinel precedent.
- **P1: preprocess unconditionally on by default.** Rejected: reopens audit C1
  verbatim - indexing a cloned repo executes its commands.
- **P2: keep the blanket env gate, document it better.** Rejected: fails the product
  requirement; the capability stays host-global and invisible per root.
- **P3: on by default under per-root trust-on-first-use.** Chosen: default-usable,
  and the enforced boundary the audit asked for.

## Constraints

- Epoch computation must stay cheap on the scoped path: hash root control files and
  config knobs directly; the nested-`.gitignore` signal must avoid a full `rglob` per
  scoped run (exact mechanism is a plan-level decision; benchmark on a large tree).
- Trust records must never live in the repo (attacker-controlled); the status-dir
  sidecar shares the existing trust root of `service.json` and the storage manifest.
- Interactive confirmation is CLI-layer only; the loader and spawn worker must never
  prompt.
- `index-workers-stay-cpu-only` and the centralized torch gate are untouched; the
  trust check needs only `hashlib`/`json`/`pathlib`.
- Parent features (scoped reindex, preprocess infra, storage manifest) are all stable
  and shipped.

## Implementation

Decision set, cited by the plan:

- **D1 - Two-tier per-root config epoch.** The code meta sidecar gains two reserved
  keys beside the embed-schema sentinel: a membership epoch (blake2b over the resolved
  `.vaultragignore` pattern list, the nested-`.gitignore` signal, and preprocess rule
  patterns) and a content epoch (blake2b over preprocess invocation fields - command,
  options, on_error, timeout - plus `html_strip`). The vault sidecar gains a content
  epoch over `vault_chunk_chars`.
- **D2 - Self-escalation at every incremental entry.** Checked inside the locked
  incremental implementations before scoped dispatch: content-epoch mismatch escalates
  to a clean rebuild; membership-epoch mismatch forces the unscoped incremental
  (which prunes newly-ignored and admits newly-un-ignored files). Epochs are stamped
  on every successful index write. First run over a legacy sidecar (missing keys)
  triggers one unscoped reconcile, not a clean rebuild.
- **D3 - Cheap epoch computation.** Root control files are read directly
  (bytes-hashed) and config knobs serialized; the nested-gitignore input reuses the
  scan the run already performs or an mtime/size-bounded signal - never an extra
  full-tree walk on the scoped path.
- **D4 - Preprocess tri-state mode.** `preprocess_mode` in config:
  `default` (on with TOFU), `trust_all` (every root runs, loudly logged), `off`
  (kill switch). Env: unset means default; `VAULTSPEC_RAG_PREPROCESS_TRUST_ALL=1`
  forces trust-all; `VAULTSPEC_RAG_PREPROCESS=off` forces off. No backwards
  compatibility (owner decision at approval): `VAULTSPEC_RAG_PREPROCESS_ENABLED` is
  removed outright - the enum entry, the config field, and the gate all go; a set
  legacy var is simply unread. Consumers migrate to the tri-state.
- **D5 - TOFU trust store.** A `preprocess-trust.json` sidecar in the managed status
  dir, keyed by root collection prefix, holding the blake2b of the resolved rule set
  (per rule: pattern, command/entry_point, on_error, priority, resolved timeout,
  options, order; canonical JSON). Atomic tmp+replace writes under a lock;
  degrade-on-corrupt to untrusted; test-isolated via the status-dir env knob.
  Re-hashed at every load, so a changed rule set reverts to untrusted (no TOCTOU).
- **D6 - Enforcement point.** `load_preprocess_rules` enforces the mode after
  resolving rules: off returns empty; trust_all returns rules with a loud log; default
  returns rules only when the hash matches a trust record, else empty plus a loud,
  actionable warning naming the trust verb. Daemon/watcher/MCP paths never prompt.
- **D7 - CLI trust verbs and flags.** `preprocess trust [PATH]` prints the resolved
  command set, confirms interactively (auto-accept with `--yes`), and persists the
  record; `preprocess untrust [PATH]` removes it; `preprocess status [PATH]` reports
  mode, hash, and trust state. `server start`, `index`, and `reindex` gain
  `--no-preprocess` / `--preprocess-trust-all`; `server start` forwards the mode into
  the daemon env like `--local-only`.
- **D8 - Operator visibility.** When a root has a preprocess config that is untrusted
  or the mode is off, `server start` output and `preprocess status` say so with the
  remediation verb; index results already carry `preprocess_skipped` counts through
  jobs.
- **D9 - Targeted watcher fixes.** The watcher re-resolves the preprocess config when
  `.vaultragpreprocess.toml` changes (admitting it in the change filter for that
  purpose only), and `.md` joins the watcher code-extension set to match the indexer's
  language map.
- **D10 - Docs.** README and `server start` help document the tri-state, the trust
  flow, and the drift-epoch self-healing behavior.

## Rationale

O3 is the only placement that makes every entry point - watcher, CLI, MCP, service -
self-healing without duplicating drift logic in adapters, and it reuses the proven
sentinel escalation path under the writer lock (research A1, A4). The two-tier split
maps each drift class to its minimal sufficient escalation (research A3): membership
drift needs only the unscoped incremental's set arithmetic; content drift invalidates
stored vectors for unchanged bytes and needs the clean rebuild. P3 satisfies the
product requirement (no per-index client action) while finally shipping the TOFU half
of the audit C1 recommendation; hashing the resolved rule set makes trust precise
(a comment edit does not re-prompt; a command change does) and self-revoking on
change (research B1, B2, B7). The owner rejected the research B4 back-compat alias at
approval: the legacy `PREPROCESS_ENABLED` knob is removed without a bridge, keeping
the control surface single-vocabulary at the cost of a one-time consumer migration.

## Consequences

- Ignore-file and preprocess-config edits reconcile automatically on the next watcher
  or CLI run; the consumer's stale-chunk class disappears. D8 of the vaultragignore
  ADR is restored under scoped reindex.
- Preprocess works out of the box after a one-time per-root trust act; the invisible
  host-global gate is gone. A BREAKING behavior change for consumers relying on unset
  meaning off: an untrusted config now warns loudly instead of silently doing nothing,
  and a trusted config runs. Additionally BREAKING: `VAULTSPEC_RAG_PREPROCESS_ENABLED`
  is removed without an alias; existing consumers setting it get the new default
  (TOFU) until they set `VAULTSPEC_RAG_PREPROCESS_TRUST_ALL=1` or trust the root.
- Residual risk, named: an operator who trusts without reading the printed command set
  re-opens RCE for that root; TRUST_ALL is deliberately alarming and logged. A
  compromised status dir could forge trust - the same boundary as every existing
  managed sidecar.
- A content-epoch change over a large corpus triggers a clean rebuild - correct but
  expensive; the preprocess output cache keyed on source hash plus command amortizes
  re-extraction.
- The audit's `preprocess-config-is-code-execution` codification candidate is
  satisfied and ready for promotion once this holds a cycle.
- Adds one small hash computation per incremental run and one trust-store read per
  rule load - both bounded and off the GPU path.
