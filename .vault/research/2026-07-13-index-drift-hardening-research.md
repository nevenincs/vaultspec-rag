---
tags:
  - '#research'
  - '#index-drift-hardening'
date: '2026-07-13'
modified: '2026-07-14'
related:
  - '[[2026-04-04-vaultragignore-adr]]'
  - '[[2026-06-02-watcher-targeted-reindex-adr]]'
  - '[[2026-06-10-preprocess-hooks-adr]]'
  - '[[2026-06-19-destructive-ops-security-audit]]'
---

# `index-drift-hardening` research: `config-drift signals and preprocess-on-by-default`

A rag consumer team reported two capability drifts: chunks of files newly ignored via
`.vaultragignore` linger in the index indefinitely under the resident watcher, and
preprocess hooks are silently inert unless `VAULTSPEC_RAG_PREPROCESS_ENABLED=1` is in
the service process env. This research grounds two hardening requirements: (1) every
per-root input that shapes index contents must be hash-tracked so drift against what
the index was built with is a dependable, self-healing reindex signal; (2) preprocess
hooks must work on by default - without per-index client action - while reconciling the
untrusted-repo RCE finding (C1) that made them off by default, with CLI-flag and
env-override control parity.

## Findings

### A. Index-configuration drift signals

#### A1. The single existing drift sentinel, and the gap class

The codebase indexer has exactly one drift sentinel today: `_needs_embed_rebuild`
(`src/vaultspec_rag/indexer/_codebase_indexer.py:1546`) compares the reserved meta key
`_EMBED_SCHEMA_KEY` against the hardcoded `_CODE_EMBED_SCHEMA` and escalates to
`_full_index_locked(clean=True)` on mismatch (`:1250-1255`). The vault indexer mirrors
this with `_needs_layout_rebuild` (`_vault_indexer.py:782-802`) against
`_VAULT_POINT_SCHEMA`. Both fire only for embed/point-schema changes - nothing tracks
the config that shapes *which* files are indexed or *how* their bytes become chunks.

The load-bearing gap: the resident watcher only ever runs **scoped** incremental
reindex (`watcher.py:406-409`), and scoped incremental keys purely off file **byte
hashes**. Any drift where file bytes are unchanged but index-shaping inputs changed -
ignore edits, preprocess-rule edits, `html_strip`/`vault_chunk_chars` flips - is never
reconciled until a manual unscoped reindex. The watcher `watch_filter`
(`watcher.py:213-216`) never even admits the scaffold files (`.vaultragignore`,
`.gitignore`, `.vaultragpreprocess.toml`), so their edits trigger no run at all.
Service restart does not help: startup runs no reconcile; only the watcher and explicit
reindex requests index.

#### A2. Inventory of index-shaping inputs (code index, per root)

Membership-shaping (which files):

- `.gitignore` - all of them, recursive: `_build_gitignore_spec`
  (`_codebase_indexer.py:153-191`) does `root_dir.rglob(".gitignore")`, prefixing
  nested patterns by relative dir, plus hardcoded prunes (`.venv/`, `.git/`,
  `.vault/`, `node_modules/`, ...).
- `.vaultragignore` - root-only (`_build_vaultragignore_spec`, `:215-247`; the
  vaultragignore ADR D2), OR-combined with gitignore (`:341-344`, D1: ignore wins,
  `.vaultragignore` can never un-ignore).
- Constructor `extra_excludes` from CLI `--exclude` - ephemeral and non-persisting;
  the resident service always builds indexers with `extra_excludes=None`
  (`service.py:601`). Excluded from any epoch, else it would thrash between CLI and
  service runs.
- `.vaultragpreprocess.toml` (membership side) - a rule match *expands* the scan set,
  admitting unsupported/oversized/binary files (`_matches_preprocess_rule`
  `:358-369`; preprocess ADR D2/D10).

Content-shaping (how bytes become chunks):

- `.vaultragpreprocess.toml` (output side) - a rule's command/options change the
  extracted text of a file whose bytes never changed.
- `html_strip` config knob (default on) - resolved in the spawn worker
  (`_chunk_worker.py:195-205`), applied to `.html` chunking.
- `_CODE_EMBED_SCHEMA` - already covered by the existing sentinel.

The meta sidecar is per-root by construction: `_meta_path` derives from
`root_dir / data_dir` (`_codebase_indexer.py:129-130`, `config.py:311` - default
`.vault/data/search-data/`), so a reserved epoch key is naturally per-root with no
cross-root contamination. (The JSON sidecars were never relocated by
storage-lifecycle; they stay under each project root.)

Vault index: membership is delegated to `vaultspec_core.scan_vault()`
(`_vault_indexer.py:485-500`) - no ignore files. The one content-shaping knob is
`vault_chunk_chars` (default 3000, chunk boundary in `_streaming.py:84`); changing it
re-chunks every doc with unchanged bytes, and `_needs_layout_rebuild` does not catch
it - the same gap class as `html_strip`.

#### A3. Drift-class to escalation matrix

Verified set arithmetic in the unscoped incremental (`_codebase_indexer.py:1298-1299`):
`new = curr - prev` admits newly-un-ignored files; `deleted = prev - curr` prunes
newly-ignored ones. So unscoped incremental reconciles *membership* drift fully, but is
blind to *content-output* drift on unchanged bytes (it keys off byte hashes).

| Drift class                                | Bytes change? | Unscoped fixes? | Required escalation      |
| ------------------------------------------ | ------------- | --------------- | ------------------------ |
| Newly-ignored file                         | no            | yes             | unscoped incremental     |
| Newly-admitted file (pattern removed)      | no            | yes             | unscoped incremental     |
| Preprocess membership (pattern add/remove) | no            | yes             | unscoped incremental     |
| Preprocess output (command/options change) | no            | no              | clean rebuild            |
| `html_strip` flip over indexed `.html`     | no            | no              | clean rebuild            |
| `vault_chunk_chars` change                 | no            | no              | clean rebuild (vault)    |
| Embed input format                         | n/a           | n/a             | clean rebuild (existing) |

#### A4. Where the check must live

Three options were evaluated for reacting to scaffold-file drift:

- (a) Admit scaffold filenames in the watcher `watch_filter` and force the next run
  unscoped - pushes drift classification into the watcher (violates
  `service-domain-owns-operability`) and leaves explicit scoped CLI/MCP callers
  unguarded.
- (b) Periodic epoch check on watcher idle ticks - wasteful rglob per tick; same
  scoped-caller gap.
- (c) **Check the epoch inside every incremental entry and self-escalate in the
  indexer** - reuses the `_needs_embed_rebuild` precedent at
  `_codebase_indexer.py:1250-1255`, runs under the already-held `_writer_lock`, and
  makes watcher, CLI, and MCP scoped callers all self-heal with zero watcher changes.
  Recommended.

Cost constraint: a naive epoch recompute would rglob every nested `.gitignore` per
scoped run, erasing the O(change) win the watcher-targeted-reindex ADR was created to
deliver. The epoch computation must stay cheap (hash the root control files and config
knobs directly; keep the nested-gitignore signal light). The exact canonicalisation and
the nested-gitignore cost/correctness tradeoff are plan-level decisions, ideally with a
large-tree benchmark.

Residual watcher gaps the epoch does not close (need their own targeted fixes): the
watcher resolves `preprocess_config` once at start (`watcher.py:204`), so a rule added
mid-session never admits its target files into the change filter; and non-vault `.md`
is indexable (`_chunking.py:161`) but absent from the watcher `_CODE_EXTENSIONS`
(`watcher.py:38-65`), so root-level markdown edits are invisible to the watcher.

#### A5. Prior art and invalidated decisions

- The watcher-targeted-reindex ADR (2026-06-02) deliberately made watcher runs scoped
  to stop O(tree) per-change work; any epoch must not reintroduce per-scoped-run
  full-tree cost.
- The vaultragignore ADR (2026-04-04) D8 decided "no watcher monitoring of
  `.vaultragignore`; edits take effect on the next index run naturally." That was true
  when every watcher run was a full incremental scan - the June scoped-reindex change
  **silently invalidated D8**: under scoped reindex an ignore edit triggers no run at
  all. The config epoch is the correct restoration of D8's intent without reverting to
  full scans. D1 (two-spec OR) and D2 (root-only) constrain what the epoch hashes.
- No existing ADR or research covers config epochs or reindex escalation beyond these.

### B. Preprocess hooks on by default

#### B1. Threat model: root registration is not a defensible trust boundary

The act that registers a root with the resident service is the routine operator action
on an unfamiliar repo, so it cannot double as consent to execute that repo's code. The
search route (`server/_routes.py:599-730`) resolves the caller's `project_root` and
calls `_ensure_watcher_soon(root)` (`:721`), starting a filesystem watcher for the
root; the reindex route (`:742-765`) indexes explicitly. Preprocess commands execute
inside `CodebaseIndexer._resolve_preprocess_context()`
(`_codebase_indexer.py:272-289`) on every full or incremental index. Two mitigating
nuances verified: a bare search on a never-indexed clone does not preprocess inline
(`api.py:378-379` short-circuits at zero chunks), and the watcher runs no initial full
index - but any watched file change after a mere search started the watcher triggers
an incremental index that runs the repo's commands. This is exactly audit C1; the
audit's recommended trust-on-first-use confirmation was never built - only the blanket
env gate at `_preprocess_config.py:228-237` shipped.

#### B2. TOFU design

- Hash the **resolved rule set**, not file bytes: `load_preprocess_rules` already
  yields deterministically ordered frozen rules (sorted `(priority, order)`,
  `_preprocess_config.py:133`). Serialize per rule `pattern`, `command`/`entry_point`,
  `on_error`, `priority`, resolved `timeout_s`, `options`, `order`; JSON
  `sort_keys=True`; blake2b. A comment/whitespace edit re-resolves identically (no
  re-prompt); a command change produces a new hash (re-prompt).
- Trust store lives in the **managed status dir, never the repo** (the repo is
  attacker-controlled): a `preprocess-trust.json` mirroring `storage_manifest.py`
  (`:98-116`) - keyed by `root_collection_prefix(root)`, atomic tmp+`os.replace`
  under a lock, degrade-on-corrupt to untrusted, isolated in tests via
  `VAULTSPEC_RAG_STATUS_DIR`.
- UX split by path, following the UNVERIFIED-binary loud-warning precedent
  (`qdrant_runtime/_supervise.py:904-926`): daemon/watcher/MCP paths never prompt -
  untrusted rules are skipped with a loud, actionable warning naming
  `vaultspec-rag preprocess trust <root>`; interactive CLI index paths print the
  resolved command set and confirm once, then persist the trust record.
- Re-hash at every load: a changed rule set reverts to untrusted automatically
  (closes the TOCTOU between trust and execution).

#### B3. Tri-state control matrix

Parity precedent is `local_only`: `EnvVar.LOCAL_ONLY` (`config.py:97`) +
`_ENV_OVERRIDE_MAP` (`:167`) + `server start --local-only`
(`_service_lifecycle.py:355-365`) forwarded into the daemon env
(`_process.py:378-379`).

| State                  | Env                                    | CLI flag                 | Behavior                                                                                                                                |
| ---------------------- | -------------------------------------- | ------------------------ | --------------------------------------------------------------------------------------------------------------------------------------- |
| Default: on with TOFU  | unset                                  | none                     | Rules load only when the resolved-set hash matches a trust record; untrusted skips with loud warning (daemon) or one-time confirm (CLI) |
| Force-on: trust-all    | `VAULTSPEC_RAG_PREPROCESS_TRUST_ALL=1` | `--preprocess-trust-all` | Every root's rules run, no trust check, loudly logged                                                                                   |
| Force-off: kill switch | `VAULTSPEC_RAG_PREPROCESS=off`         | `--no-preprocess`        | No rules ever load                                                                                                                      |

Trust records are per-root state and stay out of `config.py` (scalar knobs only);
only the mode scalar is config. New CLI verbs extend the existing `preprocess` group
(list/check/run-one today): `preprocess trust [PATH]`, `untrust [PATH]`,
`status [PATH]`. `server start` and the index/reindex verbs take the mode flags, and
`server status`/jobs surface "untrusted preprocess config - N rules skipped" so the
condition is operator-visible (service-domain-owns-operability).

#### B4. Back-compat

`src/` references to `preprocess_enabled` are only `config.py` (enum, map, default at
`:430`) and the gate at `_preprocess_config.py:228`; the rest is three test files.
Recommended mapping: `VAULTSPEC_RAG_PREPROCESS_ENABLED=1` aliases **trust-all** with a
deprecation warning (preserves existing unattended consumers exactly - they opted in
deliberately); `=0` aliases force-off; unset means on-with-TOFU (the behavioral flip).

#### B5. Rule-integrity constraints hold

The trust check lives in the indexer/config layer and needs only
`hashlib`/`json`/`pathlib`. `_preprocess_config.py` stays CPU-only and
dependency-light (module contract, `:9-15`) and is imported by the spawn chunk worker,
so `index-workers-stay-cpu-only` and the centralized torch gate are untouched.
`mcp/`, `serviceclient/`, and CLI service-control never import the preprocess config.
Interactive confirm stays strictly in the CLI layer, never in the loader or worker.

#### B6. Decisions superseded or amended

- Preprocess-hooks ADR "Trust model is decided" consideration and its "explicit, not
  enforced" honest-limit are amended: TOFU makes the trust boundary enforced.
- D3 (degrade-don't-raise error policy) unchanged - the TOFU check sits before parse;
  an untrusted config resolves to zero rules. D9 (out-of-process execution)
  reinforced. D13 (CLI verbs) extended with trust/untrust/status.
- The audit's `preprocess-config-is-code-execution` codification candidate is finally
  satisfied by this design and is past the one-cycle promotion discipline.

#### B7. Residual risk vs today

Today the capability is safe but effectively invisible: no `server start` help, no
README mention, only a daemon-log warning at reindex time. Proposed: works
out-of-the-box after a one-time per-root trust act. Residual risks, all narrow: an
operator who trusts without reading re-opens RCE (mitigated by printing the resolved
command set at the prompt and the deliberately alarming TRUST_ALL naming); a
compromised status dir could forge trust records (same trust root as `service.json`
and the storage manifest - no new boundary). Net posture is stronger than the audit's
original recommendation (which never shipped its TOFU half) and strictly more usable
than the invisible gate.

## Recommended direction

Adopt both halves as one feature:

1. **Two-tier per-root config epoch** in the meta sidecars, checked at every
   incremental entry beside the existing schema sentinels, self-escalating in the
   indexer: membership-epoch mismatch (ignore files, preprocess rule patterns) forces
   the unscoped incremental; content-epoch mismatch (preprocess invocation fields,
   `html_strip`; `vault_chunk_chars` on the vault side) forces a clean rebuild. Epoch
   computation must stay cheap to preserve the scoped-reindex O(change) win.
1. **Preprocess on by default under TOFU** with the tri-state control surface, status-
   dir trust store, CLI trust verbs, loud skip warnings on daemon paths, and the
   back-compat aliases above.
1. Targeted watcher fixes the epoch cannot provide: re-resolve `preprocess_config` on
   a `.vaultragpreprocess.toml` change; add `.md` to the watcher code-extension set.
