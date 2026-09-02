---
tags:
  - '#research'
  - '#tool-mode-cuda'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v1'
body_hash: 'sha256:8562878a0c6aa642013912a99748341b57e1a4eabd8c79e08e6933c74abcf996'
related:
  - '[[2026-07-14-tool-env-gpu-continuity-adr]]'
  - '[[2026-09-01-tool-mode-cuda-reference]]'
---

# `tool-mode-cuda` research: `durable CUDA repair in persistent tool environments`

The question is whether the installer can repair a CPU-only persistent `uv tool`
environment durably and safely. The evidence favors an installer transaction
that detects the active tool environment, requires affirmative consent, refuses
when a live or unverifiable service could hold its files, invokes uv's
receipt-carrying reinstall form, and verifies the repaired interpreter and
receipt afterward. The ADR must settle that scope and its failure contract.

## Findings

### A project repair cannot repair a tool environment

The project flow changes `pyproject.toml` and runs `uv sync` for that target,
whereas uv tools use a persistent isolated virtual environment outside the
project. The source boundary is documented by
`2026-09-01-tool-mode-cuda-reference`; uv's tool documentation independently
states that installed tools use isolated environments. Extending the project
patcher would therefore create an apparent repair that leaves the actual tool
interpreter unchanged. The current accepted continuity ADR identifies active
repair as a future pathway, so a new decision is necessary rather than a
silent implementation change.

### The durable state must travel through the tool installation request

uv documents that `uv tool install` replaces an existing tool and that upgrade
respects installation constraints and settings. The current command renderer
uses `--with` with a CUDA wheel direct URL and a matching `--python` request;
that is the only local implementation that encodes the CUDA variant, version,
platform, and free-threaded ABI together. A repair must execute a structured
form derived from that existing specification and from the tool-mode builtin,
then verify that the receipt retains the CUDA direct requirement; parsing an
emitted display string would introduce a second command model. The current
direct URL should remain the durable mechanism: upstream material indicates
index-option receipt handling has changed across uv releases, while the direct
requirement does not depend on that serialization.

### File safety requires a conservative service boundary before mutation

On Windows, uv copies tool executables, so an active service can retain handles
inside the environment the repair replaces. The existing tool guidance warns
about that condition, while the service resolver distinguishes a verified
service from a degraded machine lock. A negative status-file lookup is not
sufficient permission: a live unknown holder must prevent a destructive
reinstall. The existing identity verification has the required evidence model
and should be reused rather than adding a receipt-specific PID check.

### Consent, result reporting, and postconditions need explicit semantics

The established installer asks before mutating a project torch surface and
returns structured actions plus warnings. A tool repair needs the same
interactive/non-TTY consent posture, but its successful postcondition is not a
changed TOML file: the tool interpreter must report a CUDA-capable build and
the tool receipt must preserve the CUDA dependency for future upgrades. A
subprocess failure, unavailable uv executable, failed verification, declined
consent, active service, and degraded holder need distinct truthful outcomes.

### Alternatives narrow the decision

Keeping printed commands leaves the reported defect intact. Repairing only with
`uv pip` changes the active wheel but not the next tool re-resolution. Stopping
the service automatically expands the installer into process control and risks
ending unrelated work. Reinstalling when service evidence is incomplete can
damage a live installation. An installer-owned, consented, conservative repair
has the smallest surface that closes the durable failure.

The research did not perform a real tool reinstall against a live Windows
service or inspect uv's receipt schema on every supported uv release. Execution
must add hermetic command/result tests and a release-environment validation of
the actual receipt.

### The active installer may itself be a replacement hazard

The feature requires a real Windows execution proof after the service-held-file
guard passes. `uv tool install --force` replaces an existing tool environment,
and the installer process may itself retain handles in that environment. A
failed replacement must remain an explicit failure with no fallback to the
non-durable `uv pip` route; a handoff design is only justified if the proof
shows that the direct invocation cannot succeed.

## Sources

- `2026-09-01-tool-mode-cuda-reference`
- `2026-07-14-tool-env-gpu-continuity-adr`
- https://docs.astral.sh/uv/concepts/tools/
- https://docs.astral.sh/uv/guides/tools/
- https://docs.astral.sh/uv/reference/cli/
- https://github.com/astral-sh/uv/blob/main/crates/uv-tool/src/lib.rs
