---
tags:
  - '#research'
  - '#preprocess-sandbox'
date: '2026-07-13'
modified: '2026-07-13'
related:
  - '[[2026-07-13-index-drift-hardening-adr]]'
  - '[[2026-06-10-preprocess-hooks-adr]]'
  - '[[2026-06-19-destructive-ops-security-audit]]'
---

# `preprocess-sandbox` research: `containment replaces consent for non-interactive server hooks, and driving main green`

The owner's clients call the resident RAG **server** and are non-interactive: there is
no way to prompt for trust. The trust-on-first-use gate shipped the same day
(`3a75362`) therefore silently skips every untrusted root's rules under the server's
default mode - the client's hooks never run and nothing in the HTTP response says so.
The mandate is to make the server able to run **any** root's hooks with no security
concern, by **execution containment** rather than consent, and to drive the whole
integration suite green. This research grounds both.

## Findings

### A. The server-path silent no-op (what is actually broken)

The full server path for a client calling reindex on a root with
`.vaultragpreprocess.toml`: the HTTP `/reindex` route returns `queued` before indexing
runs, the background job resolves rules through `load_preprocess_rules`, and
`_enforce_preprocess_mode` (`_preprocess_config.py:343-356`) finds the root untrusted,
logs a daemon-only warning, and returns zero rules. Empty config means the preprocess
context is `None`, so the spawn workers never match the `.pdf`/`.html`/`.xls` sources,
which then fail the supported-extension gate and never enter the index.
`preprocess_skipped` is 0 because nothing was attempted. The client sees
`+0 /0 -0` on a `done` job - a fully silent no-op.

Only the daemon's own env governs the running daemon's mode: `preprocess_mode` reads
`os.environ` live in the daemon process, and `_service_child_env`
(`cli/_process.py:334-393`) inherits the parent shell wholesale (stripping only
`VAULTSPEC_RAG_ROOT`), so `VAULTSPEC_RAG_PREPROCESS_TRUST_ALL` is only settable at
spawn. A library client connecting to an already-running daemon cannot change the mode
without restarting it. The trust store is read fresh every load (no caching) and the
daemon resolves the same status dir as an interactive CLI, so a human running
`preprocess trust` out of band would be picked up on the next reindex - a viable
stopgap, but not "no user interaction."

Three further server-path defects, independent of trust: the watcher's change filter is
also trust-gated (an untrusted root's empty config means a watched `.pdf` edit is not
recognized as a change - a second silent surface); the `/jobs` response drops
`preprocess_failures` entirely (`jobs.py:438-445` stores only the summary string), so a
client can never see which files failed extraction; and `/reindex` has no pre-flight
notice equivalent to the one `server start` prints. Sources:
`server/_routes.py:737,765`, `jobs.py:400,420-445`, `_codebase_indexer.py:399,410,419`,
`_chunk_worker.py:174,354`.

### B. Threat model - what a hook child can do to the server host today

The runner (`_preprocess_runner.py:161-166`) calls `subprocess.Popen(argv, ...)` with
**no `env=`, no `cwd=`, no `creationflags=`**, so the hook child inherits the daemon's
entire environment and working directory. The timeout and stdout/stderr caps bound only
wall-clock and captured-output memory - nothing about what the child does. Severity
ranked:

| # | Threat | Bounded today | Severity |
| --- | --- | --- | --- |
| T1 | Secret exfiltration via env inheritance (child inherits `VAULTSPEC_RAG_QDRANT_API_KEY`, any HF/AWS/OpenAI/proxy tokens in the daemon env) | no | Critical |
| T2 | Arbitrary RCE with daemon-user privileges (that is the hook's nature) | no | Critical |
| T3 | Trust-store forgery - the child can write `~/.vaultspec-rag/preprocess-trust.json` to self-trust, or corrupt `service.json`/the storage manifest | no | Critical |
| T4 | Filesystem read (`~/.ssh`, browser cookies, `%APPDATA%`, other roots' source) | no | High |
| T5 | Network egress / C2 / exfiltration - no restriction | no | High |
| T6 | Filesystem write outside the repo (persistence, ransomware, config tampering) | no | High |
| T7 | Detached grandchildren outliving the timeout (kill reaps only the direct child) | no | High |
| T8-T11 | Registry writes, disk fill, memory/fork-bomb, CPU burn | no / partial | Medium-Low |

T1 and T3 are the sharpest and the cheapest to close (curate the child env, keep the
status dir out of it). T3's target vanishes entirely if the trust store is deleted.

### C. Containment options (Windows-first)

The repo already drives raw `ctypes` Win32 Job Objects for the qdrant child
(`qdrant_runtime/_supervise.py:207-294`), so the idiom is in-tree.

- **Job Object** (extend the existing idiom): `KILL_ON_JOB_CLOSE`, active-process and
  memory limits, breakaway off. Fixes T7/T9/T10/T11 and gives reliable process-tree
  teardown. Does not contain filesystem, network, registry, or env. Necessary, not
  sufficient.
- **AppContainer / LowBox token** (recommended containment boundary):
  `CreateProcessW` with `STARTUPINFOEX` carrying `SECURITY_CAPABILITIES{AppContainerSid}`
  is default-deny by construction - no filesystem except the container's own subtree,
  **no network unless an `internetClient` capability SID is granted** (we grant none, so
  egress and even loopback to our own Qdrant are denied), no registry, no access to
  other processes. Read of the one staged input file is granted by an ACE for the
  AppContainer SID. Works unelevated (no local-user provisioning, unlike the Codex
  restricted-token design). Fixes T1/T3/T4/T5/T6/T8. Cost is `ctypes` plumbing of the
  same order as the existing Job Object code plus the attribute list.
- Rejected: Windows Sandbox / Hyper-V (Pro-only, multi-second VM spin-up per file);
  WSL2/Docker/Podman per run (heavy external dependency, per-invocation latency over
  ~530 files).
- **Curated env + staged input + scratch cwd** is mandatory hardening under any backend
  and cheap (`env=`, `cwd=`, copy the source into a per-run temp dir), fixing T1 and
  most of T3, but it is not a boundary against hostile code for T4/T5/T6.

Cross-platform backends: Linux **bubblewrap** (`--unshare-net` for loopback-only,
`--ro-bind` the staged file, `--die-with-parent`) with a **Landlock**+seccomp fallback;
macOS `sandbox-exec` with a `(deny default)` seatbelt profile (deprecated but still what
Codex/Claude Code ship). Structure as a pluggable `HookSandbox` backend probed at daemon
start, **fail-closed in server mode**: no working backend means hooks are **refused, not
run**, because a warning-and-run default silently reopens C1 on exactly the hosts that
cannot be contained.

### D. I/O contract under sandbox

Minimal capability set: read one file, write stdout, nothing else. Staging the source
into a per-run temp dir and granting the child read of only that dir collapses the
filesystem policy to a single grantable path. Hooks that shell out to system tools
(`pdftotext`, `soffice`, `tesseract`) need to read system libraries, so a two-tier
profile is warranted: a tight default (staged file + interpreter/runtime read-only, no
network) and an opt-in `needs_system_libs` tier that additionally admits system library
dirs but still denies network and home/secret access. No known text extractor needs
egress, so network stays denied in both tiers.

### E. The amended trust model

If the sandbox contains hooks by construction, per-root trust is no longer the
server-side boundary and must not gate execution. Proposed:

- Server/daemon mode: hooks run by default, always sandboxed; no trust check; no
  backend means refuse (fail-closed).
- Keep `VAULTSPEC_RAG_PREPROCESS=off` as the operator kill switch.
- `trust_all` retires as a security concept; an opt-in, loudly-alarming
  `VAULTSPEC_RAG_PREPROCESS_UNSANDBOXED=1` replaces it for operators who deliberately
  want no sandbox on a backend-less host (default remains refuse).
- Local / in-process CLI mode (owner: the client's prerogative): sandboxed if a backend
  is available, else run with a one-line warning - not fail-closed.
- Delete the trust store: `_preprocess_trust.py`, the `preprocess trust/untrust` verbs,
  the rule-set trust hashing, and the TOFU branch. The content/membership epoch hashing
  from the drift ADR is a separate concern and stays.

This supersedes/amends the `2026-07-13-index-drift-hardening` decisions: D4 (default no
longer means TOFU, `trust_all` retired), D5 (trust store removed), D6 (enforcement moves
from the loader gate to the runner's sandbox-or-refuse), D7 (drop trust verbs, keep
`--no-preprocess`, `preprocess status` reports sandbox availability). The
`preprocess-hooks` ADR's process-isolation rationale is augmented, not superseded - its
CPU/CUDA guarantee still holds; the sandbox layers on top. This is a BREAKING change on
top of freshly-shipped work.

### F. Prior art

OpenAI Codex on Windows uses restricted tokens + synthetic sandbox-user SIDs + WFP
firewall filters + job objects (needs one-time UAC because it provisions local users);
it rejected AppContainer because its open-ended dev workflows break AppContainer's tight
default-deny - the opposite of our narrow one-file-in/JSON-out case, which AppContainer
fits and which needs no elevation. Apache Tika runs parsers in a forked child for fault
isolation but does not OS-sandbox, which is why XXE (CVE-2025-66516, CVSS 10.0) still
reaches the network via SSRF - the object lesson that fork-for-isolation is not enough;
we must fork **and** deny network. unstructured.io and Elasticsearch ingest-attachment
run extractors in-process and inherit Tika's CVE exposure. Deno's default-deny
capability model is the conceptual target for the profile in D. Sources: MS Learn
AppContainer docs, Project Zero "Understanding Network Access in Windows AppContainers"
(2021), OpenAI Codex Windows sandbox blog, Picus CVE-2025-66516 writeup.

### G. The single sandbox seam

`run_preprocessor` runs **inside** the CPU-only spawn worker; the project command is a
grandchild launched from it at `_preprocess_runner._run_bounded`'s `subprocess.Popen`
(`:161-166`), with argv from `_build_argv` (`:103-123`). That single chokepoint covers
both command and entry-point forms and every server path (full, incremental, scoped,
watcher), since all converge on `run_preprocessor`. The sandbox wraps that launch; it
must not seam at the pool boundary, where trusted worker code runs.

### H. Driving main green - root causes

The closeout's 11 integration failures resolve to one product bug and stale tests; the
2 collection errors are already fixed (`2d391f5`).

- **WP1 - qdrant local delete-resurrect (product bug, own decision).** `QdrantLocal`
  `delete_collection` (`qdrant_local.py:763-778`) does `del _collection` then
  `shutil.rmtree(..., ignore_errors=True)` without ever calling `collection.close()`.
  Each `LocalCollection` holds an open sqlite handle; `del` drops one ref but the object
  sits in a gc cycle, so on Windows the open handle makes `rmtree` raise `WinError 32`,
  which `ignore_errors` swallows - `storage.sqlite` survives, and the same-name
  `create_collection` re-reads it, resurrecting deleted points. Reproduced with raw
  qdrant-client: index 6, drop (reports gone), recreate, count is 6. Proven fix: in
  `VaultStore.drop_table`/`drop_code_table` (`store.py:709-725`), **local mode only**,
  close the collection's sqlite handle (`client._client.collections.get(name).close()`)
  before `delete_collection`, then assert the on-disk dir is gone (raise if it survives).
  Server mode is unaffected (delete is an HTTP call). The private-attr reach is
  pin-sensitive (stable 1.16-1.18); the dir-gone assertion converts any future silent
  regression into a loud failure.
- **WP2 - stale CLI-expectation tests (test defects).** Two integration tests assert
  `"Codebase"` but the CLI deliberately prints `"Source code"` since `cb37526` ("Use
  plain index summaries"); fix the assertions. Three search tests fail `assert 1 == 0`
  with empty stderr because with the resident service stopped (required for full-suite
  runs) the #202 service-first mandate prints the service-down message to stdout and
  exits 1; fix by passing `--allow-fallback` (the documented single-user escape hatch)
  or setting local-only in the fixture. Two `test_cli_ux_testimonial` tests share both
  causes. Product is correct in every case.
- **WP3 - eviction tests (test defects).** The daemon-env-allowlist hypothesis is
  disproven - the knobs reach the daemon. The real cause: `search_vault_timed`
  (`api.py:219-225`) early-returns on an empty index **before** leasing the slot (a
  deliberate perf win, `8395683`), and the tests search projects they never indexed, so
  no lease fires and LRU/idle admission never runs; the slots that do appear come from
  async watcher auto-indexing the test never synchronizes against. Fix: spawn with
  `watch=False` and index each project before searching. `test_evict_busy_returns_busy`
  is self-declared timing-flaky on both trees - under the complete-green mandate that is
  itself a defect; make it deterministic (disable watcher, index, hold a real lease open
  across the evict, assert `reason == "busy"`) or replace it with a `ServiceRegistry`
  unit test.

## Recommended direction

Author two decisions. First, `preprocess-sandbox`: run each server hook as a
staged-input, curated-env, Job-Object-wrapped **AppContainer** process (Windows-first),
behind a pluggable fail-closed `HookSandbox` backend (bubblewrap/Landlock on Linux,
seatbelt on macOS), delete the TOFU trust store, and fix the three server-path defects
(watcher trust-gating, `/jobs` failure surfacing, `/reindex` notice) so hooks run
through the service with no user interaction. Second, a store-layer decision for the
qdrant local delete-resurrect workaround (WP1), with the stale-test reconciliation
(WP2/WP3) folded into the same plan to reach complete green.
