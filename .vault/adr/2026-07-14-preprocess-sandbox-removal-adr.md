---
tags:
  - "#adr"
  - "#preprocess-sandbox-removal"
date: '2026-07-14'
related:
  - "[[2026-07-13-preprocess-sandbox-research]]"
  - "[[2026-07-13-preprocess-sandbox-adr]]"
  - "[[2026-06-10-preprocess-hooks-adr]]"
  - '[[2026-07-27-preprocess-sandbox-removal-grounding-research]]'
supersedes:
  - '2026-07-13-preprocess-sandbox-adr'
modified: '2026-07-27'
---

# `preprocess-sandbox-removal` adr: `Direct hook execution replaces OS containment: performance is the mandate` | (**status:** `accepted`)

## Problem Statement

The OS-level hook sandbox accepted the day before (`preprocess-sandbox`, `cc3d680`) makes
every server-side preprocess hook run inside a per-file AppContainer with a staged input
copy. On the primary Windows host this containment costs ~5-8s per matched file against a
~50ms/file pre-sandbox indexing baseline - roughly a 150x per-file regression. A
one production corpus indexed 640 chunks in 80 minutes under the sandbox; before it,
the same class of run was minutes. The per-invocation tax is structural: scratch-dir
staging, an `icacls` child process to ACL-grant the scratch dir, AppContainer
`CreateProcessW`, and a cold interpreter/uv startup inside a default-deny container -
plus per-worker `icacls /T` full-tree ACL walks over `sys.base_prefix`, `sys.prefix`, and
the project root whose in-memory `_GRANTED` memo does not survive a fresh spawn worker,
so every new worker pool re-walks trees whose ACEs already persist on disk.

The prior ADR rejected its own option C3 (container/VM) precisely for "multi-second
spin-up per file over hundreds of corpus files." Measurement shows the chosen C1
(AppContainer) carries that identical cost profile in practice. The owner's mandate is
unambiguous: preprocessing capability stays and stays on by default; a ~150x indexing
regression is unacceptable; the OS sandbox is removed. This ADR records that decision and
re-establishes the trust model as that of any local dev tool.

## Considerations

- Performance is the governing driver, and it is measured, not speculative: ~150x per
  matched file, 80 minutes for a 640-chunk corpus, with a per-worker ACL-walk amplifier
  that scales O(files x tree) rather than O(files).
- The accepted trust model is explicit: a repo's `.vaultragpreprocess.toml` is
  repo-authored code in the same trust class as running `make`, `npm install`, or a
  repo's own build scripts. Indexing a repo you would not build is already out of scope.
- Process isolation of the hook child is a separate, load-bearing concern from OS
  containment. The original `preprocess-hooks` ADR chose a subprocess grandchild (D6/D9)
  to keep the `index-workers-stay-cpu-only` invariant true by construction - arbitrary
  extractor code must not `import torch`/init CUDA inside a spawn worker. That subprocess
  boundary is a CPU/CUDA-correctness requirement, not a security boundary, and is
  retained untouched.
- The hardening the prior ADR bundled under C1 splits cleanly by cost. The curated child
  env (secret/knob stripping), the wall-clock timeout, the output caps, schema
  validation, and the argv-hygiene guards are near-zero cost and stay. Only the
  OS-containment layer (AppContainer, `icacls` grants, source staging, staged-path
  remapping, fail-closed refusal) carries the per-file tax and is removed.
- The non-interactive-client problem the prior ADR solved by containment is now solved by
  trust: a root's hooks run by default because indexing a repo is an act of trust in that
  repo, so no consent gate and no containment gate stands between a `/reindex` call and
  the hook running.

## Considered options

- **Remove the OS sandbox, keep direct subprocess execution.** Chosen. Restores the
  bare-process-spawn cost profile; retains process isolation, caps, and env curation;
  accepts the local-dev-tool trust model. The only option that meets the performance
  mandate while keeping preprocessing on by default.
- **Keep the AppContainer sandbox (status quo).** Rejected: the measured ~150x regression
  is the reason this ADR exists; the owner has ruled it unacceptable.
- **Optimise the sandbox in place (persist the ACL-grant memo across workers, pre-warm
  containers).** Rejected as the primary path: it attacks the per-worker re-walk
  amplifier but leaves the irreducible per-file AppContainer `CreateProcessW` +
  cold-interpreter + staging tax, the same cost that sank C3 in the prior record. It does
  not reach the baseline.
- **Persistent sandboxed hook host / per-root trust designation.** Not chosen now, not
  foreclosed. A long-lived contained hook process or a per-root trust flag could restore
  containment without the per-file tax; recorded as a future option (see Consequences),
  out of scope for this removal.

## Constraints

- The `index-workers-stay-cpu-only` invariant must continue to hold by construction: the
  hook must remain a subprocess grandchild, never in-worker Python, and every module on
  the spawn-worker import chain must keep `torch` imports lazy. This removal touches only
  the containment layer, not that boundary.
- The `preprocess-hooks` ADR D6/D9 is a parent this decision depends on and preserves;
  nothing here supersedes its process-isolation rationale.
- The `preprocess-sandbox` ADR (2026-07-13) is the direct parent being superseded. Its
  D2-D6 and the unsandboxed arm of D8 are removed; its C1-vs-C2 choice is inverted (what
  it called C2, "cheap hardening only," becomes the entire accepted posture). The
  TOFU-store deletion (its D7) and the server-path defect fixes (its D9) are unrelated to
  containment and stand.
- Removal must leave the control surface coherent: with the "unsandboxed" arm gone, the
  tri-state `preprocess_mode` collapses to `default`/`off`, and every flag/env knob
  referencing sandbox opt-out must go with it.

## Implementation

High-level shape: the hook still runs as a bounded, curated, process-isolated subprocess
grandchild launched from the CPU-only spawn worker - the OS-containment wrapper around
that launch is deleted. The decision set:

- **D1 - Remove the `HookSandbox` OS backends.** Delete `_hook_sandbox_windows`
  (AppContainer profile derivation, `CreateProcessW` with `SECURITY_CAPABILITIES`, the
  `icacls` SID grants and the `_GRANTED` memo, the Job Object wrap) and
  `_hook_sandbox_posix` (bwrap/seatbelt), plus the capability probe, backend resolution,
  and the per-worker `_backend_cache`/`_backend_unavailable` memo in
  `_preprocess_runner`.
- **D2 - Remove source staging and staged-path remapping.** Delete `stage_source` (the
  per-file scratch copy) and `_remap_staged_paths`. The hook reads the ORIGINAL source
  path directly - no copy, no scratch-to-original rewrite. Deep links in emitted output
  already point at the real file, so the remap step becomes unnecessary rather than
  merely cheaper.
- **D3 - Remove the fail-closed refusal policy.** Delete `SandboxUnavailableError`,
  `_REFUSED_REASON`, and the server-mode "refuse when no backend" branch of
  `resolve_hook_sandbox`. Server mode runs hooks directly, like local mode.
- **D4 - Remove the unsandboxed escape hatch and collapse the tri-state.** Delete
  `VAULTSPEC_RAG_PREPROCESS_UNSANDBOXED` and the `--preprocess-unsandboxed` CLI flags on
  `index` and `server start`. `preprocess_mode` becomes two-state (`default` = on, `off`
  = kill switch); the `server_mode`/`unsandboxed` parameters threaded through
  `run_preprocessor` and `preprocess_file` are dropped.
- **D5 - Keep the direct subprocess launch (process isolation retained).** The hook runs
  via the `subprocess.Popen` path (the `default_popen_handle` shape): stdout/stderr
  captured on drain threads, `wait(timeout=...)`, `kill` on expiry. This is the
  `preprocess-hooks` D6/D9 grandchild - a CPU/CUDA-correctness boundary, explicitly NOT a
  security boundary, and NOT removed.
- **D6 - Keep all zero-cost bounds and hygiene.** The wall-clock timeout, the stdout cap
  (`_STDOUT_CAP_MULTIPLIER`/`_MIN_STDOUT_CAP`), the stderr cap, `PreprocOutput` schema
  validation, the emitted-text cap, the `on_error` dispositions
  (`skip`/`passthrough`/`fail`), the `shlex` token-wise `{path}` substitution, and the
  CWE-88 leading-dash operand guard all stay unchanged.
- **D7 - Keep the curated child env.** `curated_child_env` (the allow-list env that
  strips every secret and `VAULTSPEC_RAG_*` knob) is retained: it is near-zero cost and
  keeps daemon tokens out of the hook child even though the child is otherwise
  uncontained. `PYTHONPATH=project_root` injection stays so `entry_point`/project-local
  hooks import their own module tree.
- **D8 (amended in execution) - Set the child cwd to the project root.** The first
  execution pass kept a fresh scratch temp dir as the cwd; the client validation run then
  showed all 531 hook invocations failing, because project-launcher commands (`uv run`,
  `npm exec`, `make`) resolve their project from the cwd and the pre-sandbox runner -
  the contract hooks were authored and validated against with `preprocess run-one` -
  inherited a repo cwd. The child therefore runs with the project root as its working
  directory, reading the original source path passed as an argv operand. A hook that
  writes into the repo is the project's own doing under the trust model. No source copy
  occurs.
- **D9 - Keep the output cache and the incremental hash gate.** The content-hash
  `_preprocess_cache` (keyed on `source_hash | command | schema_version`) and the blake2b
  unchanged-file gate in the incremental indexer are unchanged: an unchanged file spawns
  nothing, and a changed file that hits the cache re-chunks without re-extracting.
- **D10 - Keep the kill switch.** `VAULTSPEC_RAG_PREPROCESS=off` and the
  `--no-preprocess` flags remain the operator's way to silence a root's rules entirely.

## Rationale

The performance evidence is decisive and matches the prior record's own reasoning against
per-file containers: ~5-8s vs ~50ms per matched file (~150x), 80 minutes for a 640-chunk
corpus, amplified by per-worker full-tree `icacls` re-walks. The `preprocess-sandbox` ADR
rejected C3 for exactly this "multi-second spin-up per file over hundreds of corpus
files"; the measurement shows C1 shares that profile, so the containment premise fails on
its own performance terms on the primary host. The owner's mandate resolves the trade-off
directly: keep the capability, keep it default-on, remove the layer that costs the
regression.

Removing containment is safe under the accepted trust model, not under a claim of
technical safety: a root's `.vaultragpreprocess.toml` is repo-authored code, the same
trust class as building that repo. The retained layers are the ones that cost nothing and
earn their place - the subprocess grandchild for CPU/CUDA correctness
(`preprocess-hooks` D6/D9), the curated env to keep daemon secrets out of hook children,
and the timeout/caps/schema/argv guards to bound a misbehaving-but-trusted extractor.
What is deleted is precisely the set that carries the per-file tax. Grounding is in the
`preprocess-sandbox` research (the C-series containment options and their per-invocation
latency) and the measured production numbers above.

## Consequences

- **Performance restored.** Per matched file returns to a bare process spawn; the hook
  command's own cost (e.g. `uv run` startup) is the hook author's to own, not the
  sandbox's. Unchanged files spawn nothing (indexer hash gate + output cache). This is
  the intended and primary outcome.
- **Security posture reverts to the local-dev-tool model, stated plainly.** Audit C1
  (untrusted-repo RCE via a cloned repo whose `.vaultragpreprocess.toml` runs on watcher
  auto-index) is reopened. The residual mitigations are the curated env (no daemon
  secrets reach the child) and the wall-clock/output caps; the filesystem and network are
  open to the hook child. This is an accepted risk under the local-dev-tool trust model,
  accepted by the operator/owner: a root's preprocess config IS code execution with the
  operator's privileges, and the docs must say exactly that.
- **BREAKING control-surface change.** `VAULTSPEC_RAG_PREPROCESS_UNSANDBOXED` and the
  `--preprocess-unsandboxed` flags are removed; `preprocess_mode` is now two-state.
  Operators who set the escape hatch to run on a backend-less host no longer need it -
  hooks always run. `VAULTSPEC_RAG_PREPROCESS=off` remains the kill switch.
- **Supersedes `preprocess-sandbox` (2026-07-13).** Its D2-D6 and the unsandboxed arm of
  D8 are withdrawn; its C1 choice is replaced by what it called C2 as the whole posture.
  Its TOFU-store deletion (D7) and server-path defect fixes (D9) are independent of
  containment and remain in force. The `preprocess-hooks` D6/D9 process-isolation
  rationale is preserved verbatim, not superseded.
- **Codification reframed.** The `preprocess-config-is-code-execution` candidate reverts
  to its original framing: a root's preprocess config is code execution with the
  operator's privileges - not "runs only under a working OS sandbox or is refused." Docs
  and any promoted rule must assert the trust-based framing.
- **Pathway left open.** Nothing here forecloses a future per-root trust designation or a
  persistent sandboxed hook host that would restore containment without the per-file
  tax. That is a deliberate, non-blocking follow-up, out of scope for this removal.
