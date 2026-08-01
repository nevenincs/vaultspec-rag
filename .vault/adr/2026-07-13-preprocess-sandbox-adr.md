---
tags:
  - "#adr"
  - "#preprocess-sandbox"
date: '2026-07-13'
related:
  - "[[2026-07-13-preprocess-sandbox-research]]"
  - "[[2026-07-13-index-drift-hardening-adr]]"
  - "[[2026-06-10-preprocess-hooks-adr]]"
  - "[[2026-06-19-destructive-ops-security-audit]]"
superseded_by: '2026-07-14-preprocess-sandbox-removal-adr'
modified: '2026-07-21'
body_hash: 'sha256:40763c9f415049c9c7b154d1610f29816aa5824c3fd1328ee33a73ee6ae900f8'
---

# `preprocess-sandbox` adr: `OS-sandboxed hooks replace consent as the server boundary` | (**status:** `superseded`)

## Problem Statement

The RAG service's clients are non-interactive: they call the resident server over HTTP
and cannot answer a trust prompt. The trust-on-first-use gate shipped the same day
(`3a75362`) consequently makes the server, under its default mode, silently skip every
untrusted root's preprocess rules - the client's hooks never run and the HTTP response
shows a successful no-op. Removing that gate so hooks run by default would reopen the
untrusted-repo RCE (audit C1): the hook child today inherits the daemon's full
environment (secrets), can read and write any file the daemon can, and can reach the
network. The decision is to make the server able to run **any** root's hooks with no
security concern by containing their execution, rather than by asking a human for
consent. Derived from the `preprocess-sandbox` research; owner-approved on the two
load-bearing choices (full OS containment; delete the trust store).

## Considerations

- The single execution seam is the hook subprocess launch in the runner
  (`_preprocess_runner._run_bounded`), reached by every server path (full, incremental,
  scoped, watcher) through `run_preprocessor` inside the CPU-only spawn worker. Wrapping
  that one launch contains command and entry-point forms alike.
- The repo already drives raw `ctypes` Win32 Job Objects for the qdrant child, so the
  Windows containment idiom is in-tree and dependency-free.
- Windows is the primary host and the hard one; the service must also run on
  Linux/macOS. The sandbox must be a pluggable backend, not a Windows-only branch.
- The hook I/O contract is narrow - read one file, write stdout JSON - which is exactly
  the shape an AppContainer's tight default-deny fits (unlike open-ended dev sandboxes
  that must reject it).
- The trust store lives in the status dir, which an unsandboxed hook can currently write
  - it can forge its own trust record. Deleting the store removes that target and the
    now-purposeless consent surface.
- Process isolation (preprocess-hooks ADR D6/D9) was chosen for CPU/CUDA safety, never
  as a security boundary; the sandbox layers on top of it, it does not replace it.

## Considered options

- **C1: full AppContainer boundary.** Chosen. Default-deny filesystem and network by
  construction, unelevated, no new dependencies; the only option that closes
  filesystem-read/write, network egress, and secret access at once.
- **C2: cheap hardening only (curated env + Job Object + staged input).** Rejected as
  the boundary: closes secret theft and process-tree threats but leaves arbitrary file
  read/write and network egress open - not "no security concern." Retained as mandatory
  hardening layered under C1.
- **C3: container/VM per run (Windows Sandbox, Docker, WSL2).** Rejected: heavy
  dependency or multi-second spin-up per file over hundreds of corpus files.
- **T1: keep TOFU as the boundary.** Rejected: unreachable for non-interactive clients;
  it is the cause of the silent no-op.
- **T2: delete the trust store.** Chosen: the sandbox is the boundary, so per-root
  consent no longer gates execution, and deleting the store erases the forgery target.
- **F1: fail-open when no sandbox backend is available (warn and run).** Rejected:
  silently reopens C1 on exactly the hosts that cannot be contained.
- **F2: fail-closed in server mode (refuse to run hooks).** Chosen.

## Constraints

- AppContainer plumbing (`STARTUPINFOEX` + `SECURITY_CAPABILITIES`, ACL grant for the
  staged file, inheritable pipe handles) is Windows-specific `ctypes` work of the same
  order as the existing Job Object supervisor; it is the highest-risk element and must
  be proven with a real end-to-end test that a contained child cannot read outside the
  staged dir nor open a socket.
- The sandbox code must stay CPU-only and importable from the spawn-worker chain (no
  torch), consistent with `index-workers-stay-cpu-only`.
- The private qdrant-client coupling and other store concerns are out of scope here;
  the integration-suite-green work owns them.
- Backends must degrade predictably: server mode refuses without a working backend;
  local/in-process CLI mode runs sandboxed-if-available else warns (the client's
  prerogative, per the owner).

## Implementation

Decision set, cited by the plan:

- **D1 - Single sandbox seam.** A `HookSandbox` abstraction wraps the subprocess launch
  in `_preprocess_runner`. `run_preprocessor` asks the resolved backend to spawn the
  hook; the backend owns argv wrapping, env, cwd, and teardown. All existing bounds
  (timeout, stdout/stderr caps, argv hygiene) are preserved inside it.
- **D2 - Staged input + curated env + scratch cwd (all backends).** The source file is
  copied into a per-run temp dir; the child runs with cwd set there, an env stripped to
  a minimal safe set (no `VAULTSPEC_RAG_*` secrets, no inherited tokens), and read
  access limited to the staged dir. This is mandatory hardening under every backend and
  the sole filesystem grant the OS sandbox must make.
- **D3 - Windows AppContainer backend.** Launch via `CreateProcessW` with an
  AppContainer SID and no network capability, so filesystem (outside an ACL-granted
  staged dir), network (including loopback), and registry are denied by construction,
  wrapped in a `KILL_ON_JOB_CLOSE` Job Object for process-tree teardown and
  memory/process limits.
- **D4 - Pluggable cross-platform backends.** Linux bubblewrap (`--unshare-net`,
  `--ro-bind` the staged file, `--die-with-parent`) with a Landlock+seccomp fallback;
  macOS `sandbox-exec` with a deny-default profile. A capability probe at daemon start
  selects the backend.
- **D5 - Two-tier capability profile.** A tight default (staged file + interpreter
  runtime read-only, no network) and an opt-in `needs_system_libs` tier that additionally
  admits system library directories for hooks that shell out to `pdftotext`/`soffice`
  and similar - network stays denied in both.
- **D6 - Fail-closed server mode.** When server mode resolves no working sandbox
  backend, hooks are refused with a loud, actionable log and surfaced status, never run
  unsandboxed. Local/in-process CLI mode runs sandboxed-if-available, else with a
  one-line warning.
- **D7 - Delete the TOFU trust store.** Remove `_preprocess_trust.py`, the
  `preprocess trust`/`untrust` verbs, the rule-set trust hashing, and the trust branch
  of the loader gate. `load_preprocess_rules` no longer trust-gates; rules resolve for
  any root. The content/membership epoch hashing from the drift ADR is unrelated and
  stays.
- **D8 - Amended control surface.** `VAULTSPEC_RAG_PREPROCESS=off` remains the kill
  switch. `trust_all` retires; an opt-in, loudly-alarming
  `VAULTSPEC_RAG_PREPROCESS_UNSANDBOXED=1` lets an operator deliberately run without a
  sandbox on a backend-less host (default is refuse). `preprocess status` reports the
  resolved sandbox backend and whether hooks will run, replacing the trust report;
  `--no-preprocess` stays.
- **D9 - Server-path defect fixes.** The watcher change filter must recognize
  preprocessable files regardless of the old trust state (it followed the loader gate);
  `IndexResult.preprocess_failures` must be threaded into the job record and the `/jobs`
  response so a client can see which files failed extraction; and `/reindex` gains a
  pre-flight signal when a root ships a config, mirroring the `server start` notice.

## Rationale

Containment is the only boundary that survives a non-interactive client: if the child
genuinely cannot exfiltrate, read secrets, or reach the network, running any root's
hook by default is safe and no consent is needed (research B, C, E). AppContainer is the
one Windows option that denies filesystem and network by construction while staying
unelevated and dependency-free, and the hook's one-file-in/JSON-out contract is the
narrow shape it fits where open-ended sandboxes reject it (research C, F). Fail-closed
is the correct default because a fail-open fallback silently reopens C1 on the very
hosts that cannot be contained (research C). Deleting the trust store follows directly:
once the sandbox is the boundary, per-root consent gates nothing and its store is only
an attack target (research E). The prior art is decisive - Tika's fork-without-sandbox
still yields CVSS-10 SSRF (CVE-2025-66516), so fork-and-deny-network is the minimum bar
(research F).

## Consequences

- Hooks run through the service with no user interaction, contained by construction; the
  silent no-op disappears and the consumer's corpus indexes.
- BREAKING, on top of the same-day `3a75362`: `VAULTSPEC_RAG_PREPROCESS_ENABLED` was
  already removed there; now the trust store, the `trust`/`untrust` verbs, and
  `trust_all` are removed too. Operators on a host with no sandbox backend must set
  `VAULTSPEC_RAG_PREPROCESS_UNSANDBOXED=1` or hooks are refused.
- Supersedes/amends `2026-07-13-index-drift-hardening`: D4 (default now means
  on-sandboxed, `trust_all` retired), D5 (trust store removed), D6 (enforcement moves
  from the loader to the runner), D7 (trust verbs dropped, `preprocess status`
  repurposed). The drift epoch decisions (D1-D3, D9-D10 of that ADR) are untouched. The
  `preprocess-hooks` ADR D6/D9 process-isolation rationale is augmented, not superseded.
- The AppContainer backend is Windows-specific `ctypes` and the primary implementation
  risk; the fail-closed default means a host where it does not work refuses hooks
  (safe) rather than running them unconfined, so an incomplete backend never degrades
  security - only availability.
- Residual risk, named: local kernel/LPE and AppContainer loopback-bypass CVE classes;
  extractor bugs that corrupt output within the granted capability (contained to a
  per-file skip by schema validation); and full re-exposure of C1 only if an operator
  sets the `UNSANDBOXED` escape hatch (deliberately alarming, opt-in, logged).
- The `preprocess-config-is-code-execution` codification candidate is reframed:
  execution is now safe by containment, so the rule should assert "server-mode hooks run
  only under a working OS sandbox or are refused," not "only when trusted."
