---
tags:
  - '#research'
  - '#tool-env-gpu-continuity'
date: '2026-07-14'
modified: '2026-07-19'
related: []
---

# `tool-env-gpu-continuity` research: `surviving uv tool upgrades on a GPU box`

A field report from a GPU (cu130) Windows 11 box running v0.2.28 as a uv tool
(`uv tool install "vaultspec-rag[mcp]"`) surfaced two regressions and two UX gaps:

- **R1:** `uv tool upgrade vaultspec-rag` (or `install --force`) re-resolves the tool
  env and replaces `torch==2.13.0+cu130` with the CPU PyPI wheel every time; the next
  `server start` refuses ("service interpreter has a CPU-only torch wheel"), and the
  printed remediation (`vaultspec-rag install`) is a two-step indirection - on a tool
  env that command punts to the escape hatch
  (`uv pip install --python <tool python> --reinstall --torch-backend=cu130 torch`),
  which is what actually works. The GPU pin is effectively unmanaged across upgrades.
- **R2:** a `uv tool install --force` while the service was running failed mid-removal
  (the running service exe holds `Scripts\`), after which `uvx vaultspec-rag` silently
  resolved to a cached ephemeral env (`uv\cache\archive-v0\...`) with CPU torch - the
  CPU-wheel refusal persisted even after the real tool env was repaired, and nothing
  indicated the interpreter was not the installed tool.
- **UX-a:** during model warmup `server status` reports "stopped" while `server start`
  reports "a service already owns this machine" - no warming state.
- **UX-b:** `server jobs` always prints "N active, M waiting", so scripted greps for
  "active" self-deadlock; jobs has no `--json`.

This research grounds the fixes in (1) uv tool-environment mechanics (external) and
(2) the existing install/gate/lifecycle/jobs code (in-repo).

## Findings

### External: uv tool-environment mechanics (uv 0.9.x, mid-2026)

- **U1 - Tool receipts record install options and `uv tool upgrade` re-applies them.**
  Each tool env carries `<UV_TOOL_DIR>/<name>/uv-receipt.toml` with a `[tool.options]`
  table recording `--index` entries and `--with` packages/constraints; upgrade
  re-consults them (astral-sh/uv issue 11929 demonstrates the shape and the
  re-application, and the tools docs state upgrades respect install-time constraints).
  Therefore `uv tool install "vaultspec-rag[mcp]" --index https://download.pytorch.org/whl/cu130` yields upgrades that keep CUDA torch. This is
  the durable fix vector.
- **U2 - A bare `--index` is a blunt instrument; a `--with` direct-URL is sharper.**
  A recorded `--index` becomes the highest-priority index for ALL packages (workable
  because the pytorch index serves only torch/vision/audio, PyPI stays as fallback),
  and `explicit=true` + `[tool.uv.sources]` pins cannot be expressed through the tool
  CLI (sources are project-file-only). The index-independent alternative is a PEP 508
  direct reference: `--with "torch @ https://download.pytorch.org/whl/cu130/torch-2.13.0%2Bcu130-cp313-cp313-win_amd64.whl"`,
  fully recorded and re-applied, and it sidesteps a known Windows `--index` breakage
  for the pytorch index (astral-sh/uv issue 11532). Cost: the URL hard-pins version,
  python ABI, and platform.
- **U3 - `--torch-backend`/`UV_TORCH_BACKEND` is `uv pip`-only.** The pytorch guide
  states it verbatim; extension requests to `uv add` (14236, 12994) are unshipped and
  none tracks `uv tool`. The existing escape hatch is therefore the only
  torch-backend-shaped repair, and it must target the tool python explicitly.
  Source: docs.astral.sh/uv/guides/integration/pytorch/.
- **U4 - uv has no post-install/upgrade hook for tools.** Confirmed absent from the
  tools concept and guide docs; any re-pin logic must live in the recorded install
  spec (U1/U2) or in vaultspec-rag's own detection/remediation surfaces.
- **U5 - uvx ephemeral fallback is silent and detectable.** `uvx` uses the installed
  tool env only when the request matches the installed spec and the env is healthy;
  otherwise it silently builds/reuses an ephemeral env under the uv cache
  (`.../uv/cache/archive-v0/...`) - including when the installed env is broken or
  partially removed (the locked-`Scripts\` case; astral-sh/uv issue 15333 documents
  the split and the slippage). Runtime detection on Windows: installed env prefix
  lives under `uv tool dir` (default `%APPDATA%\uv\tools\<name>`, `UV_TOOL_DIR`
  override); an ephemeral prefix contains `archive-v0` under the uv cache
  (`%LOCALAPPDATA%\uv\cache`, `UV_CACHE_DIR` override). `sys.prefix` inspection is
  sufficient to classify, no uv subprocess needed for the positive `archive-v0` case.
- **U6 - Prior art.** Astral's first-class pytorch recommendation is project-scoped
  (`[[tool.uv.index]] explicit=true` plus `[tool.uv.sources]`) - exactly the thing
  that does not survive into published wheels, which is why R1 exists. No surveyed
  PyPI-distributed GPU CLI has a cleaner mechanism than (a) a documented receipt-
  carrying install one-liner, (b) a `--with` direct-URL pin, or (c) self-detection
  plus an exact-command remediation. This is an acknowledged uv gap.

### In-repo: current install/gate/lifecycle/jobs behaviour

Two bug-report claims need correction before deciding anything: `server jobs`
**already has `--json`** (UX-b only bites scripts that grep the human output), and
the UX-a contradiction is real and structural (the daemon holds the machine lock
through model warmup but uvicorn does not accept connections until warmup finishes,
so `/health` is unreachable exactly while the lock says "owned").

- **F1 - The CPU-wheel refusal is a subprocess pre-flight and already prints the
  interpreter path.** `_probe_daemon_cuda(interpreter)` in
  `src/vaultspec_rag/cli/_process.py` (444-505) runs a `-c` probe subprocess and maps
  exit codes (3 torch absent, 4 "the service interpreter has a CPU-only torch wheel
  (no CUDA)", 5 CUDA build but no visible device). The probed interpreter comes from
  `_resolve_daemon_interpreter()` (`_process.py` 420-441): the launching env's
  Scripts python via `sysconfig.get_path("scripts")`, fallback `sys.executable` - the
  daemon runs in whatever env launched it. The refusal itself is
  `_preflight_daemon_cuda` in `src/vaultspec_rag/cli/_service_lifecycle.py` (270-306,
  called at 590 before spawn): it prints `Service interpreter: {interpreter}`, "That
  environment cannot run the GPU-only service: {reason}.", and next-actions pointing
  at `vaultspec-rag install` - which on a tool env only re-prints the escape hatch
  (F2), confirming R1's two-step indirection.
- **F2 - The installer never repairs a tool env; it only warns the escape hatch.**
  Tool-env detection is `_running_in_uv_tool_env()` in
  `src/vaultspec_rag/cli/_gpu_errors.py` (78-89): `sys.prefix` parent directory named
  `tools`. `vaultspec-rag install` patches the *project* pyproject
  (`commands/_torch_flow.py`) and then calls `warn_if_active_torch_not_gpu()`
  (`cli/_install.py` 312-315); on a CPU-only tool env that prints (`_gpu_errors.py`
  112-167) the exact working command: `uv pip install --python "{sys.executable}" --reinstall --torch-backend=cu130 torch`. The cu130 pin is the project-scoped
  `[tool.uv.sources]` + `[[tool.uv.index]] pytorch-cu130` pair, absent from published
  wheel metadata - so any bare tool-env resolve pulls CPU torch from PyPI (matches
  U3/U6).
- **F3 - Nothing classifies the uvx ephemeral env.** The only env classifier is
  `_running_in_uv_tool_env()`; `archive-v0` has zero matches in `src/`. A uvx-cache
  run has `sys.prefix` at `uv/cache/archive-v0/<hash>/`, whose parent is the hash, so
  the tool-env test returns False and start silently pre-flights (and would spawn)
  the ephemeral CPU env. The only diagnostic is the printed `Service interpreter:`
  line - exactly the manual comparison the reporter had to make.
- **F4 - The warming gap is the lifespan ordering.** In
  `src/vaultspec_rag/server/_lifespan.py`: `acquire_machine_lock()` first (124), then
  qdrant + model warmup (134), and only then `yield` to uvicorn (136). `server start`'s guard reads `machine_lock_live_holder()` (`_service_lifecycle.py` 412-431:
  "A vaultspec-rag service already owns this machine (pid {holder}).") - fires during
  warmup. `server status --port` classifies via `_explicit_port_state(port_listening, health)` (`_service_lifecycle.py` 1840-1848): health ready means running, port
  listening means unreachable, **else "stopped" (exit 3)** - and during warmup the
  port is not accepting, so status says stopped while start says owned. No warming
  state exists anywhere (grep finds only `warmup`, never `warming`).
- **F5 - Jobs already has `--json`; it just is not the lifecycle envelope, and the
  human summary always contains "active".** CLI `service_jobs`
  (`cli/_service_jobs.py` 1036-1157) has `--json` returning the raw service payload;
  the human summary line (508-513) is "Displayed jobs: {n} active, {m} waiting, ..."
  plus a legend, both always containing the literal word `active`. The data comes
  from `GET /jobs` (`server/_routes.py` 496-563, server-side filtering) with the CLI
  a thin adapter - already conformant with `service-domain-owns-operability`. The
  sibling start/stop verbs emit `{ok, command, data:{status,...}}` envelopes; jobs
  emits a plain `_emit_json(True, "service.jobs", data=result)`.
- **F6 - Test homes.** Pre-flight/env refusal: `tests/test_service_env_preflight.py`
  (no-mock probe-vs-truth pattern; natural home for env-classification tests).
  Start/stop envelopes: `test_cli_server_start.py`, `test_cli_server_stop.py`,
  `test_service_stop_port.py`. Status states: `test_cli.py` status fixtures. Jobs:
  `test_jobs_unit.py` + `integration/test_service_jobs.py`. Installer/tool-env:
  `test_install_torch_config.py`, `test_install_provision.py`, `test_provision.py`,
  `integration/test_install.py`. Lock-vs-lifespan ordering:
  `test_lifespan_machine_lock.py`, `integration/test_machine_singleton.py`.

## Synthesis

R1 and R2 share one root cause: at start time nothing distinguishes *which*
environment will run the daemon (installed tool env, uvx ephemeral cache env, or
project venv), and the refusal's remediation points at `vaultspec-rag install`, which
on any non-project env cannot repair anything - it only re-prints the escape hatch
the operator eventually needs. UX-a is independent (a missing lock-held-but-not-yet-
serving state). UX-b is the smallest: JSON already exists; the residual gaps are the
non-envelope shape and discoverability.

## Options

- **O1 - Make the pin survive upgrades via the tool receipt (fixes R1 at the
  root).** Document and emit the receipt-carrying install form
  (`uv tool install "vaultspec-rag[mcp]" --index https://download.pytorch.org/whl/cu130`,
  or the `--with` direct-URL wheel pin) as the canonical tool-install command; per U1
  the receipt re-applies it on every `uv tool upgrade`. vaultspec-rag cannot write
  the receipt itself (U4: no hooks), so the deliverable is the remediation surfaces:
  the CPU-wheel refusal and `warn_if_active_torch_not_gpu` should print the
  receipt-fixing one-liner (which makes future upgrades safe) alongside the
  immediate escape hatch (which repairs the env in place but is undone by the next
  upgrade).
- **O2 - Single-step remediation (fixes R1's indirection).** `_preflight_daemon_cuda`
  already knows the interpreter and can classify the env (F2/F3 helpers): print the
  exact working `uv pip install --python "{interpreter}" --reinstall --torch-backend=cu130 torch` command directly in the refusal instead of routing
  through `vaultspec-rag install`. Optionally an explicit `vaultspec-rag install --repair-env` (or `server doctor --fix-torch`) that *runs* the escape hatch against
  the resolved interpreter after confirmation.
- **O3 - Classify the runtime env and warn on ephemeral (fixes R2 diagnosis).** Add
  an env classifier (installed-tool / uvx-ephemeral / project-venv / other) keyed on
  `sys.prefix` vs `uv tool dir` and the `archive-v0` cache shape (U5). `server start`
  (and the refusal) prints a loud warning when the interpreter is ephemeral: "you are
  running a cached uvx environment, not the installed tool; reinstall with the
  service stopped". Cheap, pure-path logic, no uv subprocess needed for the positive
  case.
- **O4 - Refuse-or-diagnose the locked reinstall (fixes R2 cause).** vaultspec-rag
  cannot intercept `uv tool install --force` (U4), so the achievable half is
  documentation plus the O3 warning; optionally `server stop` guidance in the
  ephemeral warning ("the Scripts lock is the running service itself").
- **O5 - A warming state (fixes UX-a).** Either write a `warming` phase into the
  status sidecar before warmup starts (the CLI parent already writes service.json at
  spawn; the daemon could stamp phase transitions), or start uvicorn before warmup
  and have `/health` report `warming` - the latter is a larger lifecycle change and
  interacts with readiness semantics; the sidecar phase is the bounded option.
  `_explicit_port_state` then renders lock-held + sidecar-warming as "warming (pid,
  since)" instead of "stopped", and exits with a distinct code.
- **O6 - Jobs envelope + discoverability (fixes UX-b residual).** Align `server jobs --json` with the `{ok, command, data:{...}}` lifecycle envelope shape per
  `broker-facing-cli-outcomes-are-structured-and-idempotent`, and mention `--json` in
  the human summary/help so script authors find it instead of grepping "active".

## Open questions

- Q1: Should the canonical documented tool-install command carry `--index` (simple,
  version-floats with upgrades, blunt priority) or the `--with` direct-URL wheel pin
  (robust, sidesteps uv issue 11532, but hard-pins version/ABI/platform and must be
  kept in step with the workspace cu130 pin)? Affects README, install docs, and the
  emitted remediation strings.
- Q2: Should O2's active repair (`install --repair-env` running the escape hatch) be
  in scope, or is exact-command emission enough for v1? Running `uv pip install`
  against an arbitrary resolved interpreter is a mutating act with its own failure
  modes.
- Q3: For O5, is the sidecar-phase approach acceptable given the status file is
  currently written by the CLI parent at spawn - i.e. who owns the `warming` ->
  `running` transition stamp, the daemon lifespan or the parent poller?

## Sources

- astral-sh/uv issues 11929 (receipt `[tool.options]` re-application), 11532
  (Windows pytorch `--index` breakage), 15333 (uvx ephemeral vs installed env),
  12000/16196/11117 (cache staleness traps); docs.astral.sh/uv
  guides/integration/pytorch, concepts/tools, reference/environment,
  reference/storage.
- In-repo: `src/vaultspec_rag/cli/_process.py` 420-505,
  `src/vaultspec_rag/cli/_service_lifecycle.py` 270-306, 412-431, 1840-1848,
  `src/vaultspec_rag/cli/_gpu_errors.py` 36-167, `src/vaultspec_rag/cli/_install.py`
  312-315, `src/vaultspec_rag/server/_lifespan.py` 39-52, 124-136,
  `src/vaultspec_rag/cli/_service_jobs.py` 508-525, 1036-1157,
  `src/vaultspec_rag/server/_routes.py` 496-563, at commit `4faee6a`.
- Field report: user session 2026-07-14 (v0.2.28, Windows 11, cu130).
