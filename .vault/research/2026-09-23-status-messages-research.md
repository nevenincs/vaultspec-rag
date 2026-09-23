---
tags:
  - '#research'
  - '#status-messages'
date: '2026-09-23'
modified: '2026-09-23'
body_schema: 'body-v2'
body_hash: 'sha256:da7d135c835d8828dd7717ca9e001efb34dc0a958f8fd7fbc9f4c5eba619f461'
related:
  - "[[2026-06-11-service-status-convergence-adr]]"
  - "[[2026-09-01-gpu-less-install-footprint-adr]]"
  - "[[2026-09-04-cuda-provisioning-adr]]"
  - "[[2026-09-21-typesafe-classifier-adr]]"
  - "[[2026-06-10-preprocess-hooks-adr]]"
  - '[[2026-04-12-vaultspec-rag-install-adr]]'
  - '[[2026-04-22-install-cuda-adr]]'
  - '[[2026-06-01-service-observability-adr]]'
  - '[[2026-06-13-provisioning-setup-adr]]'
  - '[[2026-06-13-server-first-default-adr]]'
  - '[[2026-06-24-service-doctor-liveness-adr]]'
  - '[[2026-07-14-tool-env-gpu-continuity-adr]]'
  - '[[2026-07-21-preprocess-batch-hooks-adr]]'
  - '[[2026-07-22-service-health-client-hardening-adr]]'
  - '[[2026-08-26-mcp-read-only-mode-adr]]'
  - '[[2026-09-08-search-readiness-contract-adr]]'
  - '[[2026-06-11-service-status-convergence-research]]'
  - '[[2026-09-01-gpu-less-install-footprint-research]]'
  - '[[2026-09-04-cuda-provisioning-research]]'
  - '[[2026-09-21-typesafe-classifier-research]]'
  - '[[2026-06-10-preprocess-hooks-research]]'
  - '[[2026-09-08-search-readiness-contract-research]]'
  - '[[2026-09-23-status-messages-adr]]'
---

# `status-messages` research: `Canonical installation role, compute and feature state for status reporting`

Question: why do `vaultspec-rag status` and `vaultspec-rag server status` report
confusing or wrong operator state? The clearest case: on a workstation with an RTX 4080
SUPER, the installed tool prints `Compute: Unavailable (no CUDA or MPS accelerator; CPU
is unsupported)`. A second question is what a plain-language status redesign has to
build on. The redesign must also show which optional features are active for the
current repository, such as a preprocessing hook or Typesafe classification.

Conclusion: the wrong message is a symptom. The root cause is that the package has no
canonical, typed model of operator-facing state. Four things are affected:

- **Installation role.** Is this environment a client or an inference host?
- **Compute capability.** Can the hardware, the torch build and the service actually
  run inference?
- **Per-root feature enablement.** Is a preprocessing hook active? Is Typesafe enabled?
  What storage mode, watcher and reranker are in effect?
- **Service lifecycle and health.**

Each of these is re-derived independently in several modules, mostly as bare strings
and untyped dicts, and often in the client process instead of the service. The accepted
`2026-06-11-service-status-convergence-adr` already requires one service-domain status
model with CLI, HTTP and MCP only adapting it. The code does not yet comply with that
decision.

## Findings

### The reported GPU failure is an install defect rendered as a hardware verdict

- **The installed tool environment has a CPU-only torch build.** Its uv receipt requests
  `vaultspec-rag[mcp,gpu]` with no CUDA wheel pin, and it resolved `torch 2.14.0+cpu`
  (`torch.version.cuda` is `None`). The dev venv on the same host has `2.14.0+cu130`.
  This matches the documented risk: a bare install resolves torch from the public index
  (`README.md:72-84`). Nothing flagged the substitution at install time.
- **`status` falls back to probing its own interpreter.** With the service stopped, it
  calls `api.get_status` in the CLI process (`src/vaultspec_rag/cli/_status.py:299-346`).
  That probes the local torch (`src/vaultspec_rag/api.py:850-892`), and nothing in the
  output says the source changed.
- **One message covers every failure.** A single `else` branch
  (`src/vaultspec_rag/cli/_status.py:233`) collapses four states into one
  hardware-sounding line: torch absent by design (client), CPU-only build (broken host),
  genuinely no accelerator, and probe not attempted. `diagnose_torch` separates only
  a CPU-only build, no GPU, and working (`src/vaultspec_rag/torch_config/_diagnose.py:8-29`).
  `TorchDiagnosis.NO_TORCH` exists but is produced only by the CLI's own import checks.
  Nothing types absent-by-design versus defect, or marks a probe that was never
  attempted. A test locks the string (`src/vaultspec_rag/tests/test_cli_status.py:63`).
- **Nothing reads the hardware independently of torch.** `nvidia-smi` appears only in
  remediation prose (`src/vaultspec_rag/cli/_gpu_errors.py:224,327`,
  `src/vaultspec_rag/_gpu_admission.py:141`). No surface can say "an RTX 4080 is present
  but this install cannot use it."

### Installation role exists in documentation only

- **The docs define four roles.** `README.md:51-57` and `docs/installation.md:55-61`
  list: base (CLI client), `[mcp]` (MCP client), `[gpu]` (inference host) and `[gpu,mcp]`
  (combined host). The accepted `2026-09-01-gpu-less-install-footprint-adr` refers to
  control-plane and service-client surfaces but defines no persisted role.
- **"Mode" in code means three unrelated things.** None of them is the role:
  - placement `tool | dependency | dev`
    (`src/vaultspec_rag/commands/_mode.py:63-149`, persisted in
    `.vaultspec/workspace.json`)
  - storage backend local or server (`src/vaultspec_rag/config/_settings.py:1030`,
    persisted as a host-global `local-only.json`,
    `src/vaultspec_rag/config/_paths.py:22,51`)
  - index support profile (`src/vaultspec_rag/index_profiles.py:199-254`, set by
    environment only)

  `docs/installation.md:310` states that placement does not decide torch.
- **The server has no environment of its own.** It runs in whatever environment
  launched the CLI (`src/vaultspec_rag/cli/_process.py:391`). The role of the
  environment the user runs therefore silently decides whether a host is possible.
- **The installer assumes provider intent.**
  - Torch configuration and provisioning default to on
    (`src/vaultspec_rag/cli/_install.py`).
  - In dependency mode, the torch patch adds a direct `torch>=2.4` to a consumer
    `pyproject.toml` (`src/vaultspec_rag/commands/_torch_flow.py:276`).
  - The MCP tool-mode launch spec is `[gpu,mcp]`
    (`src/vaultspec_rag/builtins/mcps/vaultspec-rag.builtin.json:6`), although the
    stdio adapter loads no model.
  - Prebuilt binaries always bootstrap `[gpu,mcp]` (`tools/binaries/build_pyapp.py:111`).
  - No client-only channel exists.
- **The role is inferred from torch importability in at least nine places:**
  - `src/vaultspec_rag/cli/_process.py:452-570`: a subprocess exit-code probe,
    classified afterwards by prose equality `detail == outcome[1]`
  - `src/vaultspec_rag/commands/_tool_torch.py:378-399`
  - `src/vaultspec_rag/cli/_gpu_errors.py:250-425`
  - `src/vaultspec_rag/cli/_service_start.py:540-583`
  - `src/vaultspec_rag/_readiness.py:296-379`
  - `src/vaultspec_rag/_gpu.py:127`
  - `src/vaultspec_rag/embeddings.py:440-447`
  - `src/vaultspec_rag/_gpu_admission.py:114,412`
  - `src/vaultspec_rag/api.py:850`

  Only `_tool_torch` honours the accepted `2026-09-04-cuda-provisioning-adr` rule that
  torch absent by design is a state, not a defect. `warn_if_active_torch_not_accelerator`
  and `_torch_readiness` report a correct client as broken.

### Compute capability has four probes and four vocabularies

- **Four probes:**
  - `api._get_status`, in whichever process calls it
  - `ServiceRegistry.health()["cuda"]` (`src/vaultspec_rag/service.py:1311`). This means
    "the loaded model is on CUDA", so it reads false on MPS and while models are unloaded.
  - `_readiness._torch_readiness`, run client-side by `server doctor`
    (`src/vaultspec_rag/cli/_service_doctor.py:59`). The server's `/readiness` route is
    never called by a client.
  - the `server start` subprocess probe
- **Three overlapping vocabularies:** `TorchDiagnosis`
  (`src/vaultspec_rag/torch_config/_constants.py:80`), probe exit codes 0/3/4/5/6/7
  (exit 7 has no enum member), and admission `REASON_*` constants.
- **Three phrasings of "no accelerator":** `_gpu.ACCELERATOR_REQUIRED_MESSAGE`,
  `src/vaultspec_rag/_readiness.py:369` and `src/vaultspec_rag/cli/_status.py:233`.

### Feature enablement is resolved but never reported per root

- **Preprocessing hooks.**
  - Rules live in a repo-root `.vaultragpreprocess.toml`
    (`src/vaultspec_rag/indexer/_preprocess_config.py:62`). A mode switch comes from
    `VAULTSPEC_RAG_PREPROCESS` (`src/vaultspec_rag/config/_types.py:180`), and the
    daemon inherits it from `server start --no-preprocess`.
  - The resolved model `ResolvedIndexPolicy`
    (`src/vaultspec_rag/indexer/_resolved_policy.py:395`, built by `resolve_index_policy` at `:596`) exists, but "hooks will run"
    is re-derived at least seven times, and the copies disagree. For example,
    `src/vaultspec_rag/server/_routes_reindex.py:102` requires the file to be present,
    while `src/vaultspec_rag/indexer/_content_discovery.py:495` does not.
  - `preprocess status` reads the CLI process's mode, not the daemon's
    (`src/vaultspec_rag/cli/_preprocess.py:342-362`).
  - The only service exposure is inside a `/reindex` response. `status`,
    `server status`, `/health`, `/service-state` and the MCP index-status tool do not
    report hooks.
- **Typesafe.**
  - It is enabled only by `VAULTSPEC_RAG_TYPESAFE_API_KEY`, read directly from the
    environment (`src/vaultspec_rag/search/_typesafe_transport.py:69`).
  - Its state is untyped strings `off|pending|active|rejected|cooldown`
    (`src/vaultspec_rag/search/_typesafe_transport.py:97-130`), re-keyed by hand in
    `src/vaultspec_rag/cli/_status_labels.py:29-43`.
  - The status read resets the circuit on a key-fingerprint change, so reading has a
    side effect (`src/vaultspec_rag/search/_typesafe_transport.py:71-78`).
  - It appears on `/health` and `server status` but is not declared on
    `HealthResponse` (`src/vaultspec_rag/server/_models.py:196`), and it is absent from
    project `status`.
- **Other features with no per-root report:**
  - storage mode (local or server)
  - watcher enabled vs running. `/service-state` returns it, but `status` keeps only
    `result["index"]` (`src/vaultspec_rag/cli/_status.py:310`).
  - reranker and sparse enabled vs loaded. A deliberately disabled reranker renders as
    "not ready".
  - model identities
  - content policy. The `status` "Policy:" line never prints because `api._get_status`
    emits no policy, and the MCP `get_index_status` docstring promises one it does not
    return (`src/vaultspec_rag/mcp/_tools.py:671`).
  - MCP read-only, which is known only to the stdio shim.
- **Per-service switches and per-root facts are mixed.** Per-service: Typesafe,
  reranker, watcher enablement, preprocess mode, support profile. Per-root: hook rules,
  watcher running, content policy. No surface separates the two scopes.

### State is carried as strings and dicts across the operator surface

- **Service lifecycle has four derivations:**
  - `src/vaultspec_rag/serviceclient/_status.py:212`
  - `src/vaultspec_rag/cli/_status_render.py:256`, which has its own crashed tokens and
    labels
  - `src/vaultspec_rag/cli/_status_render.py:987` and `:1068`. Any non-`ready` health
    on a listening port becomes `unreachable`, so paused or degraded reads as a fault.
  - `src/vaultspec_rag/cli/_service_doctor.py:152`, where warming reads as
    `needs_restart`
- **"Warming" means three things:** service startup, operator verdict, and quiesce
  resume.
- **Health is one undeclared string** (`src/vaultspec_rag/server/_lifespan.py:923-997`).
  The CLI tests for values the server never emits (`starting`, `unknown`,
  `src/vaultspec_rag/cli/_status_labels.py:328`). Degradation reasons are prose that the
  CLI maps back to families by substring
  (`src/vaultspec_rag/cli/_status_labels.py:574-585`).
- **The wire is typed only for `/search`.**
  - `/health`, `/readiness`, `/service-state`, `/jobs`, `/watcher` and `/storage/survey`
    return hand-built dicts.
  - The typed models `IndexStatus` and `HealthResponse`
    (`src/vaultspec_rag/server/_models.py:126-262`) are used only by tests.
  - `serviceclient` returns `dict | None` throughout.
  - `api._get_status` carries duplicate alias keys: `cuda`/`accelerator_backend`,
    `gpu_name`/`accelerator_name`, `vram_*`/`memory_*`.
- **Labels are scattered across modules.**
  - `_status_labels.py`
  - `serviceclient/_status.py`
  - the doctor, watcher, provisioning and TUI pill tables
  - `RuntimeEnvKind.label`

  The same wording is duplicated in several places. "Not reported by service" renders
  about ten times for a stopped server (`src/vaultspec_rag/cli/_cli_format.py:49`).
- **Non-actionable lines.** `Support profile`, `Accepted backends`, `Minimum RAM` and
  the Code/Document capacity lines on `status` are static ceilings from config
  (`src/vaultspec_rag/index_profiles.py:199-254`). They are not measurements, and when
  the service is down they come from the client's config.

### Probe cost and placement

- **The full probe is expensive.** The isolated interpreter probe imports torch and calls
  `torch.cuda.is_available()` with a 60 s timeout
  (`src/vaultspec_rag/cli/_process.py:452-512`). An equivalent import plus CUDA check
  measured about 2.0 s warm, against about 0.06 s for a bare interpreter. The package
  `__init__` is lazy, so torch is the whole cost. Running it on every stopped-service
  `status` would be a large regression.
- **Cheaper signals exist.** The torch build tag (`+cpu`, `+cu130`) and the
  inference-stack distributions are readable from package metadata without importing
  torch. The probe already decides client-ness this way, through the
  `sentence-transformers` distribution (exit 6).
- **`nvidia-smi` is cheap but can hang.** It measured about 90 ms per call on this
  host, but it can block until its timeout. That is too costly for every `/health` poll.
- **The daemon interpreter can differ from the CLI's.**
  `_resolve_daemon_interpreter` picks the scripts-directory python, which can differ
  from `sys.executable` (`src/vaultspec_rag/cli/_process.py:391`). A service may also
  already be running from another environment. On this host, a service started from the
  dev venv (`+cu130`) would look healthy while the tool environment (`+cpu`) would fail
  its next `server start`.
- **Per-root policy resolution is too heavy for status.** `resolve_index_policy` walks
  the tree for ignore files (`src/vaultspec_rag/indexer/_ignore_specs.py:35-65`) and
  loads preprocess rules strictly, so it raises on a malformed config. The accepted
  preprocess-hooks decision says a bad config degrades instead.
- **Liveness is only visible from the client.** Crashed, stale-heartbeat and
  reused-PID states come from the discovery file and port probes. A service that is
  down cannot author them (`src/vaultspec_rag/serviceclient/_status.py:212-260`).
- **Doctor imports torch in the CLI process.** `server doctor` calls `get_readiness`,
  which calls `_torch_readiness`, which imports torch in-process
  (`src/vaultspec_rag/_readiness.py:296-379`). That already breaks the torch-free
  service-control constraint.

### Existing canonical patterns to extend

The package already has correct shapes that fragmented siblings do not use:

- `JobState` with behaviour properties (`src/vaultspec_rag/job_models.py:75-157`).
- The search-readiness chain: StrEnums in `src/vaultspec_rag/_search_state.py:68-99`,
  `extra="forbid"` pydantic content models in `src/vaultspec_rag/mcp/_tools.py:115-175`,
  and a renderer that derives no new verdict.
- `ReadinessReport`, a typed service-domain report serialised once.
- The `compose_discovery_status` pure composer, which returns state, label and exit
  code together.
- `ServiceVersionVerdict`, a verdict object carrying reason, remediation and
  serialisation (`src/vaultspec_rag/serviceclient/_compat.py:87`).
- `RuntimeEnvKind.label`, an enum that owns its label.
- The import-time pin tying `QuiesceTransitionCode` to its subset
  (`src/vaultspec_rag/service_quiesce.py:84-110`).

### Option space the ADR must settle

- **Installation role.** Options: persist the role at install time, or derive it once
  from typed inputs (installed extras, torch build, hardware presence) in one
  service-domain function. Persisting is explicit but can drift from the environment.
  Deriving is always true but needs a hardware probe that works without torch; NVML or
  `nvidia-smi` are candidates, and that is not yet investigated.
- **Where status is computed.** Options: the service owns every verdict and a stopped
  service yields an explicit typed "service stopped" state, or the client composes a
  local verdict that is typed and labelled as local. The accepted convergence ADR
  favours service ownership. The open question is what a client may say about itself
  when no service answers.
- **Vocabulary.** One StrEnum per concept, with label and remediation owned by the enum
  or a single table:
  - installation role
  - compute capability (collapsing `TorchDiagnosis`, probe exit codes and admission
    reasons)
  - service lifecycle
  - health verdict and degradation reason
  - feature state, split into per-service and per-root sections
- **Wire contract.** Typed pydantic response models for `/health` and `/service-state`,
  parsed into the same models by `serviceclient`, with MCP passing the typed model
  through. This retires the unused models and the dict aliases.
- **Scope of the first change.** The whole state model at once, or role, compute and
  feature state first with lifecycle, health and degradation in follow-on Steps under
  the same plan.

Not investigated: the MPS path on real Apple hardware, remote-Qdrant deployments, and
the cost of a torch-free hardware probe on each platform.

## Sources

- `README.md:51-84`
- `docs/installation.md:55-61`
- `docs/installation.md:310`
- `tools/binaries/build_pyapp.py:111`
- `src/vaultspec_rag/tests/test_cli_status.py:63`
- `src/vaultspec_rag/api.py:850-931`
- `src/vaultspec_rag/api.py:1387-1466`
- `src/vaultspec_rag/cli/_status.py:89-124`
- `src/vaultspec_rag/cli/_status.py:197-346`
- `src/vaultspec_rag/cli/_status_labels.py:29-43`
- `src/vaultspec_rag/cli/_status_labels.py:328`
- `src/vaultspec_rag/cli/_status_labels.py:574-585`
- `src/vaultspec_rag/cli/_status_render.py:256`
- `src/vaultspec_rag/cli/_status_render.py:987`
- `src/vaultspec_rag/cli/_status_render.py:1068`
- `src/vaultspec_rag/cli/_cli_format.py:49`
- `src/vaultspec_rag/cli/_service_doctor.py:59`
- `src/vaultspec_rag/cli/_service_doctor.py:152`
- `src/vaultspec_rag/cli/_process.py:391`
- `src/vaultspec_rag/cli/_process.py:452-570`
- `src/vaultspec_rag/cli/_gpu_errors.py:224-425`
- `src/vaultspec_rag/cli/_service_start.py:540-583`
- `src/vaultspec_rag/cli/_install.py`
- `src/vaultspec_rag/cli/_preprocess.py:342-362`
- `src/vaultspec_rag/commands/_mode.py:63-149`
- `src/vaultspec_rag/commands/_torch_flow.py:276`
- `src/vaultspec_rag/commands/_tool_torch.py:378-399`
- `src/vaultspec_rag/builtins/mcps/vaultspec-rag.builtin.json:6`
- `src/vaultspec_rag/config/_settings.py:1030`
- `src/vaultspec_rag/config/_paths.py:22-100`
- `src/vaultspec_rag/config/_types.py:180`
- `src/vaultspec_rag/torch_config/_diagnose.py:25-29`
- `src/vaultspec_rag/torch_config/_constants.py:80`
- `src/vaultspec_rag/_readiness.py:296-379`
- `src/vaultspec_rag/_gpu.py:127`
- `src/vaultspec_rag/embeddings.py:440-447`
- `src/vaultspec_rag/_gpu_admission.py:114`
- `src/vaultspec_rag/_gpu_admission.py:141`
- `src/vaultspec_rag/_gpu_admission.py:412`
- `src/vaultspec_rag/service.py:1311`
- `src/vaultspec_rag/server/_lifespan.py:923-997`
- `src/vaultspec_rag/server/_models.py:126-262`
- `src/vaultspec_rag/server/_routes_reindex.py:102`
- `src/vaultspec_rag/indexer/_preprocess_config.py:62`
- `src/vaultspec_rag/indexer/_resolved_policy.py:395-644`
- `src/vaultspec_rag/indexer/_content_discovery.py:495`
- `src/vaultspec_rag/indexer/_ignore_specs.py:35-65`
- `src/vaultspec_rag/search/_typesafe_transport.py:69-130`
- `src/vaultspec_rag/serviceclient/_status.py:212`
- `src/vaultspec_rag/serviceclient/_compat.py:87`
- `src/vaultspec_rag/index_profiles.py:199-254`
- `src/vaultspec_rag/job_models.py:75-157`
- `src/vaultspec_rag/_search_state.py:68-99`
- `src/vaultspec_rag/mcp/_tools.py:115-175`
- `src/vaultspec_rag/mcp/_tools.py:671`
- `src/vaultspec_rag/service_quiesce.py:84-110`
- The torch build observations (`2.14.0+cpu` in the uv tool environment, `2.14.0+cu130`
  in the dev venv) were read directly on the host on 2026-09-23. They are local
  observations, not re-fetchable locators.
