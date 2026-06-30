---
tags:
  - '#exec'
  - '#qdrant-server-provisioning'
date: '2026-06-12'
modified: '2026-06-30'
related:
  - '[[2026-06-12-qdrant-server-provisioning-plan]]'
---

# `qdrant-server-provisioning` `P05` summary

The feature promotes Qdrant server mode from an accepted escape hatch to a managed,
supervised topology with first-use binary provisioning - the architectural
successor that removes the one remaining hard cap from the concurrency rework (the
pure-Python local store's GIL-bound brute-force scans). All twelve plan steps are
closed; the code review passed with three MEDIUM findings fixed in-branch.

- Modified: `src/vaultspec_rag/store.py`, `src/vaultspec_rag/config.py`,
  `src/vaultspec_rag/server/_lifespan.py`, `src/vaultspec_rag/cli/_app.py`,
  `src/vaultspec_rag/cli/_service_lifecycle.py`, `src/vaultspec_rag/cli/_process.py`
- Created: `src/vaultspec_rag/qdrant_runtime/` (constants, resolve, provision,
  supervise), `src/vaultspec_rag/cli/_service_qdrant.py`,
  `src/vaultspec_rag/tests/test_qdrant_runtime.py`,
  `src/vaultspec_rag/tests/integration/test_qdrant_server_mode.py`

## Description

What landed, against the design:

- Pinned, verified provisioning. A new runtime package downloads the platform
  release binary on first use into a managed versioned dir, HTTPS host-pinned to
  upstream with a committed SHA256 verified before extraction and re-verified
  before execution. The pin (1.18.2) is held as a reviewed code constant with all
  six platform digests, gated against the locked qdrant-client minor by a test that
  parses the real lockfile. Local mode stays the zero-dependency default; the
  binary is never fetched without an explicit verb or a consented start flag.
- Supervised child. One shared loopback-bound Rust server hosts every root's data,
  namespaced by a per-root collection prefix, spawned before model load and stopped
  last among data components, with a Windows Job Object kill-on-close orphan guard,
  bounded readiness polling, and one bounded auto-restart with degraded-state
  surfacing in health.
- Operator surface. A `server qdrant install/status/clean` group with the sync
  vocabulary, dry-run preview, and JSON envelope; `server start --qdrant` with an
  explicit-consent provisioning gate that never downloads silently.
- Store seam. The existing backend-aware locking already takes no point-operation
  locks in server mode; this feature only adds the per-root namespacing, leaving
  the search/index business logic unchanged.

Verification: the qdrant_runtime unit suite (32 tests, including the security
negative-tests added in review - host/scheme refusal, redirect downgrade,
archive traversal, pre-exec digest mismatch) passes; the real-binary integration
suite proves the index+search round trip, two-root namespacing, and clean
shutdown end to end (it failed only transiently under a genuinely full system
disk, not a code defect). The operator persona pass passed in human and JSON
modes. The controlled big-corpus performance A/B is staged as a deliberate
follow-on operation rather than run against a contended, stale-state shared
service (see the S11 record). The code review passed; SEC-04 (redirect downgrade),
LIFE-02 (env restore), and TEST-01 (security tests) were fixed and re-tested.

Codification candidate from this feature: `pinned-binaries-verify-before-execute`

- any provisioned native binary must be SHA256-verified against a committed pin
  before extraction and re-verified before execution.
