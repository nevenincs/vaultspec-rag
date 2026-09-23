---
tags:
  - '#adr'
  - '#status-messages'
date: '2026-09-23'
modified: '2026-09-23'
body_schema: 'body-v2'
body_hash: 'sha256:771233f97379cdfc8547a5fe8a6030b4261708aca5bfd17bb50aadada7cb3a44'
related:
  - "[[2026-09-23-status-messages-research]]"
  - "[[2026-06-11-service-status-convergence-adr]]"
  - "[[2026-09-01-gpu-less-install-footprint-adr]]"
  - "[[2026-09-04-cuda-provisioning-adr]]"
  - "[[2026-09-21-typesafe-classifier-adr]]"
  - "[[2026-06-10-preprocess-hooks-adr]]"
  - "[[2026-09-08-search-readiness-contract-adr]]"
  - "[[2026-06-24-service-doctor-liveness-adr]]"
---

# `status-messages` adr: `canonical typed operator state model` | (**status:** `accepted`)

## Problem Statement

Operator status output is wrong and hard to read. On a GPU workstation, `vaultspec-rag
status` reports a hardware failure when the real cause is a CPU-only torch build in the
installed tool environment. The root causes are the ones established in
`2026-09-23-status-messages-research`:

- **No canonical model.** Installation role, compute capability, feature enablement,
  service lifecycle and health have no canonical, typed model.
- **Repeated derivations.** The same verdicts are re-derived in many modules as bare
  strings and untyped dicts.
- **Wrong process.** Verdicts are often computed in the client process rather than the
  service.

The accepted `2026-06-11-service-status-convergence-adr` already requires one
service-domain status model, and the code does not comply with it.

A plain-language redesign of `status` and `server status` cannot be built correctly on
fragmented state. The redesign must also make the features active for the current
repository clear, such as preprocessing hooks and Typesafe classification. This record
decides the state model that the redesign renders.

## Considerations

- **Roles exist in docs only.** The installation roles (CLI client, MCP client,
  inference host, combined host) are documented but modelled nowhere in code
  (`2026-09-23-status-messages-research`, installation-role findings).
- **The daemon interpreter may not be the CLI's.** The daemon runs in the interpreter
  `_resolve_daemon_interpreter` selects, which can differ from the CLI's own. A running
  service may come from a different environment altogether (research, probe cost and
  placement).
- **Absent torch is not a defect.** Torch absent by design is a state
  (`2026-09-04-cuda-provisioning-adr`, D4). Most consumers still report it as a defect.
- **Service-control paths must stay torch-free.** A compute verdict about a local
  environment must come from an isolated probe, never an in-process import. The full
  probe costs about 2 s, while metadata-only signals are nearly free (research, probe
  cost and placement).
- **Some facts are visible only from the client.** Liveness faults (crashed, stale
  heartbeat, reused PID) cannot be authored by a service that is down.
- **Good precedents already exist:** `JobState`, the search-readiness enums and models,
  `ReadinessReport`, `ServiceVersionVerdict` and `compose_discovery_status` (research,
  canonical patterns).
- **Feature state has two scopes.** Per-service: Typesafe, reranker, sparse, watcher
  enablement, preprocess mode, storage backend and models. Per-root: preprocess rules
  and watcher running. Today the two are never separated.

## Considered options

- **A. Patch the messages in place.** Fix the `else` branch at
  `src/vaultspec_rag/cli/_status.py:233`, add feature lines and reword labels. It is
  cheap, but it leaves every duplicate derivation in place and the next surface drifts
  again. Rejected.
- **B. Persist an installation role at install time.** This makes the role explicit, but
  the persisted value drifts as soon as a user adds or removes an extra or replaces the
  torch wheel. It also adds a fourth persisted "mode" beside placement, storage and
  support profile. Rejected.
- **C. Define a typed state model once in the service domain and derive each verdict in
  exactly one place, with CLI and MCP only rendering.** Every verdict is derived from
  typed inputs, and each concept has exactly one implementation. It costs a broad,
  phased refactor across the status surfaces and their tests. Chosen.
- **D. Add NVML (`nvidia-ml-py`) as a dependency for hardware detection.** It is
  precise, but it adds a native-binding dependency to every install, clients included.
  Rejected in favour of a bounded `nvidia-smi` read plus a platform check for Apple
  Silicon. Neither needs a new dependency.

## Constraints

- **CLI and MCP stay torch-free.** Local compute and role verdicts come only from the
  isolated interpreter probe (`src/vaultspec_rag/cli/_process.py:452-544`), run against
  the daemon interpreter. `server doctor`'s torch axis moves off the in-process
  `_torch_readiness` import onto that probe. When a service answers, doctor reads the
  service-reported verdict instead. The dependency axis the doctor-liveness decision
  requires is kept.
- **Every external probe is bounded.** A timeout or unexpected result becomes an
  `UNKNOWN` member and never renders as a hardware failure.
- **`nvidia-smi` rules.** Resolve it through `shutil.which`, call it in argv form with no
  shell, and give it a hard timeout. It is a driver utility, not a binary the product
  provisions, so the pinned-binary rule does not apply.
- **`/health` stays lightweight and ungated**
  (`2026-06-11-service-status-convergence-adr`). The hardware probe runs once at service
  startup, is cached, and is exposed on `/service-state` only.
- **JSON lifecycle envelopes keep one envelope per exit.** Their fields change from
  duplicate alias keys to enum values.
- **No compatibility aliases survive.** These are deleted in the same change that
  replaces them:
  - dict alias keys (`cuda`, `gpu_name`, `vram_*`);
  - the unused pydantic models;
  - the duplicate CLI lifecycle derivations;
  - prose-equality probe classification.
- **A malformed preprocess config degrades, never raises**
  (`2026-06-10-preprocess-hooks-adr`).

## Implementation

**A torch-free, service-domain state package owns every operator-facing vocabulary.**
Each concept is a `StrEnum` that owns its human label and remediation, following
`JobState` and `RuntimeEnvKind.label`. Existing canonical enums are reused, never
duplicated: `JobState`, `QuiesceState`, `SearchAvailability`, `SearchFreshness` and
`ReadinessStatus`. The new vocabularies are:

- **`InstallRole`**: `CLIENT` or `HOST`. It is decided by one function, from whether the
  inference-stack distributions are present. The MCP extra is a separate boolean
  attribute of the installation, not a role.
- **`HardwarePresence`**: `NVIDIA_GPU`, `APPLE_SILICON`, `NONE` or `UNKNOWN`. It carries
  the device name and memory when known.
- **`ComputeCapability`**: one member per state below. It replaces the overlap between
  `TorchDiagnosis`, the probe exit codes and the torch reasons in GPU admission.

  | Member | Meaning | Today's probe signal | Blocks `server start` |
  | --- | --- | --- | --- |
  | `NOT_APPLICABLE` | client install | exit 6 | yes |
  | `READY` | full probe passed | - | no |
  | `BUILD_PRESENT` | CUDA or MPS torch build installed, device not yet verified | metadata-only check | no |
  | `TORCH_MISSING` | torch absent on a host | exit 3 | yes |
  | `TORCH_IMPORT_FAILED` | torch installed but fails to import | - | yes |
  | `CPU_ONLY_BUILD` | CPU-only torch build | exit 4 | yes |
  | `NO_DEVICE` | CUDA build, no visible device | exit 5 | yes |
  | `MPS_POLICY_REFUSED` | MPS visible, accelerator policy refused | exit 7 | yes |
  | `INTERPRETER_MISSING` | daemon interpreter not found | - | yes |
  | `UNKNOWN` | timeout or unexpected result | timeout, unexpected | no |

  Device-load admission states (below floor, device unreadable, load in progress) stay
  runtime admission outcomes, not compute members.
- **`ServiceLifecycle`**: `STOPPED`, `STARTING`, `RUNNING`, `CRASHED_PID_DEAD`,
  `CRASHED_PID_REUSED`, `CRASHED_PORT_SILENT`, `CRASHED_HEARTBEAT_STALE` and
  `DISCOVERY_DEGRADED`. Each member carries its broker exit code (0, 3, 4, 5). It is
  produced by extending the existing `compose_discovery_status` in the torch-free
  service-client package, the one place that composes discovery facts with the typed
  health model. The CLI's own `_compute_state`, the port-only ternaries and doctor's
  `live` are deleted.
  - `STARTING` means models loading at startup.
  - `QuiesceState.WARMING` means resuming after a pause and renders as "resuming". The
    two are never labelled alike.
- **`HealthVerdict`**: `READY`, `PAUSED`, `DEGRADED` or `ERROR`. It comes with
  `DegradationReason` members:
  - `JOB_STALLED`
  - `JOB_FAILED`
  - `QUARANTINED`
  - `STORE_CARRIED_ACROSS`
  - `VECTOR_SERVICE_UNAVAILABLE`
  - `NONCONFORMING`
  - `MODELS_NOT_LOADED`

  The server emits these codes, and the CLI's substring family matching is deleted. A
  paused or degraded service on a listening port is never rendered as unreachable.
- **`FeatureState`** has per-service and per-root sections.
  - **Per-service:**
    - `TypesafeState`: `OFF`, `PENDING`, `ACTIVE`, `REJECTED` or `COOLDOWN`;
    - reranker and sparse, each enabled and loaded;
    - watcher enabled;
    - preprocess mode;
    - storage backend;
    - model identities.
  - **Per-root:**
    - `PreprocessHookState`: `NONE`, `ACTIVE`, `DISABLED` or `INVALID_CONFIG`, with the
      rule count;
    - whether the watcher is running for this root.
  - One predicate over the preprocess rules and the execution mode is the only
    derivation of "hooks will run". The seven existing derivations, including
    `preprocess status`, call it. It loads rules leniently and never walks the tree.
  - The Typesafe read becomes pure. It compares the credential fingerprint without
    changing it and reports `PENDING` when the key has changed.

**Who authors each verdict:**

- **Service:** its own role, hardware, compute, health and features. Hardware is probed
  once at startup. Compute and role come from its own interpreter.
- **Service-client package:** lifecycle, from discovery facts plus the service's typed
  health.
- **CLI and MCP:** render these typed models and derive nothing.

**`/health` and `/service-state` return typed pydantic models with extra fields
forbidden**, and `serviceclient` parses them into the same models. MCP
`get_index_status` returns the typed model. Its docstring promise of a content policy is
removed, and so is the dead "Policy:" line.

**When no service answers**, status shows a typed `STOPPED` lifecycle plus facts about
the local installation, labelled as local:

- role and `ComputeCapability`, from a metadata-only probe of the daemon interpreter
  that never imports torch;
- a bounded, cached hardware read.

`--verbose`, `server doctor` and `server start` run the full probe, which yields `READY`
or a specific defect.

When a service answers, status compares the service's reported interpreter with the
local daemon interpreter and shows a one-line note when they differ. Index counts are
read locally only when the storage backend is local.

**Rendering.** One label table per concept, owned by the enum, feeds plain-language
output:

- `status` and `server status` open with a short overview: service, this installation,
  compute, active features and next action. Detail stays behind `--verbose`.
- The support-profile ceilings leave the default view.
- A stopped service renders as one plain line.
- The jobs TUI health and lifecycle pills consume the same enums.
- `server doctor`, the post-install warning and the `server start` preflight consume the
  same `InstallRole` and `ComputeCapability`.

The change lands in phases under one plan, vocabulary first, so each phase deletes the
derivations it replaces.

**Out of scope:**

- installer defaults, client-only distribution channels, and the MCP tool-mode launch
  extras;
- the `--local-only` override;
- a content-policy configuration surface;
- MCP read-only mode, which only the stdio shim knows, so no status surface reports it;
- provisioning and watcher-command label tables beyond what the shared enums replace.

## Rationale

Option C is the only one that removes the root cause. Every symptom in
`2026-09-23-status-messages-research` comes from a verdict computed in more than one
place, or in the wrong process, and carried as an untyped value:

- the false hardware failure;
- a paused service reading as unreachable;
- a warming service reading as needing restart;
- a disabled reranker reading as not ready;
- disagreeing "hooks will run" answers.

Deriving role and compute from the daemon interpreter, instead of persisting them, keeps
status true to the environment that would actually serve. Splitting the metadata probe
from the full probe keeps the default `status` fast without guessing. Extending
`compose_discovery_status` puts lifecycle where liveness is actually observable, rather
than asking a stopped service to describe itself. Typed wire models make the
service-client contract checkable rather than assumed. The approach extends patterns the
codebase has already proven.

## Consequences

- **Gains:**
  - status that names the actual condition, such as "GPU host: RTX 4080 SUPER detected,
    torch is a CPU-only build", with its fix;
  - features visible per repository on both status surfaces;
  - one place to change each verdict or label;
  - typed MCP and JSON payloads;
  - doctor no longer imports torch in the CLI.
- **Costs:**
  - a broad refactor across CLI status, doctor, service start, `serviceclient`, server
    health and state routes, the MCP index-status tool, the jobs TUI and their tests;
  - tests that assert today's exact strings are repointed at the new labels, never
    relaxed.
- **Breaking changes:** JSON consumers of `status --json`, `/health`, `/service-state`
  and `get_index_status` lose alias keys and gain enum-valued fields. Release notes must
  call this out.
- **Pitfalls:**
  - `nvidia-smi` may be absent on hosts with a working GPU, so `UNKNOWN` must never
    render as a failure;
  - `BUILD_PRESENT` must never be rendered as verified;
  - enum members must be exhaustive at every render site, which tests enforce.
- **Opens:** a follow-on decision on install-flow role intent can target a named
  `InstallRole`.
