---
tags:
  - '#reference'
  - '#monitor-provisioning'
date: '2026-10-13'
modified: '2026-10-13'
body_schema: 'body-v2'
body_hash: 'sha256:7ad6534b43cd95670c09dc28eb9486085630edd35ca6670ade9869378d4f4103'
related: []
---

# `monitor-provisioning` reference: `monitor acquisition for wheel installs`

How the compiled monitor reaches an installation today, why pure-Python wheel installs cannot start the service, and which release and provisioning seams a wheel-carried pin design would touch. Pinned at commit `3de3a45e` on main, 2026-10-13. Sources: `.github/workflows/publish.yml`, `binaries.yml`, `acquisition.yml`, `tools/monitor/build.py`, `release.py`, `acquire.py`, `provenance.py`, `tools/binaries/build_pyapp.py`, `tools/packaging/products.py`, `src/vaultspec_rag/qdrant_runtime/`, `src/vaultspec_rag/monitor_process.py`, `src/vaultspec_rag/_program_lookup.py`, `src/vaultspec_rag/config/`, `src/vaultspec_rag/commands/_provision.py`.

## Summary

### Failure on wheel installs

- Service start resolves the monitor from `VAULTSPEC_RAG_MONITOR_BINARY`, else the installation scripts directory, else PATH, and fails the coupled start when none is found (`src/vaultspec_rag/monitor_process.py:37-60`, `src/vaultspec_rag/_program_lookup.py:49-59`).
- The wheel is `py3-none-any` and packages no monitor; `pyproject.toml` names no monitor artifact. Only the per-target binary bundle carries it (`tools/packaging/products.py:149-156`).
- Observed 2026-10-13: a `uv tool run` cache environment had `vaultspec-rag.exe` and `vaultspec-search-mcp.exe` but no monitor, and start failed with the missing-executable error. The installed tool environment worked only because a development-build monitor had been copied into its scripts directory by hand.
- The monitor path override has no paired digest variable, unlike the Qdrant operator pair (`src/vaultspec_rag/config/_types.py:40`, `src/vaultspec_rag/config/_registry.py:149-151`; Qdrant pair at `src/vaultspec_rag/config/_types.py:207,211`, exercised in `src/vaultspec_rag/tests/test_config_operator_binary.py:118-141`). No digest is re-checked before the monitor spawns.

### Release pipeline order

- The wheel is built once in `publish.yml` (`.github/workflows/publish.yml:178`), smoke-tested (`:189`), attached to the draft release (`:260-344`), which dispatches `binaries.yml`.
- `binaries.yml` downloads that exact wheel from the draft and checks it against `SHA256SUMS` rather than rebuilding (`.github/workflows/binaries.yml:110-116,144-167`).
- The frontend job builds Vite output once (`.github/workflows/binaries.yml:207-264`). Its `needs: [validate, wheel]` is ordering only; it consumes no wheel bytes.
- The native matrix job embeds the wheel into the RAG commands via PyApp and separately compiles the monitor (`.github/workflows/binaries.yml:266-397`, `:364-370`). `compile_monitor` reads only the frontend handoff, the pinned Bun toolchain and the checkout (`tools/monitor/build.py:158-201`). Producer identity is git HEAD and the release tag (`tools/monitor/build.py:41-77`), never wheel metadata.
- The bundle packs the wheel-embedding commands and the monitor together, so bundling must follow the wheel regardless of monitor timing (`.github/workflows/binaries.yml:384-389`).
- `admit-package-index` re-derives wheel and sdist digests from the draft's `SHA256SUMS` for PyPI publication and reads nothing monitor-related (`.github/workflows/publish.yml:362-468`). Wheel smoke tests do not reference the monitor (`.github/workflows/publish.yml:254-258`).
- No test asserts the wheel is pure-Python or that the wheel precedes binaries; `tools/binaries/build_pyapp.py:131-144,176-191` checks only wheel count, project name and version. The ordering exists only as workflow topology.

### Published monitor assets

- Only per-target bundle archives and the checksum aggregate cross the release edge; raw target-qualified executables stay private build intermediates (`.github/workflows/binaries.yml:495-499`).
- `acquisition.yml:193` uploads `dist-bin/vaultspec-rag-monitor-*` as CI evidence only, not as a release asset.
- Public acquisition downloads the whole bundle archive (`tools/monitor/acquire.py:104-162`) and admits it by `gh attestation verify` against the fixed signer workflow, tag ref and commits, then reads the monitor digest from the authenticated `manifest.json` (`tools/monitor/provenance.py:18,70-123`). There is no committed monitor pin table.
- The bundle embeds the wheel, so a bundle-archive digest cannot be known when the wheel is built.
- The Windows x64 monitor executable measured 90,198,016 bytes in a local development build (`dist-bin/vaultspec-rag-monitor-x86_64-pc-windows-msvc.exe`).

### Reusable provisioning primitives

- `download_https` is HTTPS-only, host-pinned across redirects, time- and size-bounded, and retries only transient failures (`src/vaultspec_rag/qdrant_runtime/_download.py:657-737`). Monitor CI tooling already calls it (`tools/monitor/acquire.py:35-42`).
- `file_sha256`, `verify_native_binary` and `extract_verified_archive` (`src/vaultspec_rag/qdrant_runtime/_provision.py:165-178,421-476`) are imported unmodified by `tools/monitor/build.py:36` and `tools/monitor/acquire.py:28-32`.
- Qdrant-specific: the static pin tables (`src/vaultspec_rag/qdrant_runtime/_constants.py:81-144`), managed-binary classification (`src/vaultspec_rag/qdrant_runtime/_managed_install.py:254-283`) and the install/upgrade/dry-run state machine (`src/vaultspec_rag/qdrant_runtime/_provision.py:1237-1317`).
- `server start` provisioning wires Qdrant through `src/vaultspec_rag/commands/_provision.py:876-995`, and reports through the shared `ProvisionOutcome`/`ProvisionStepResult` machinery (`src/vaultspec_rag/commands/_provision.py:166-289`), which is the "Provisioning: ... Qdrant binary" status block.
- Qdrant verifies the executable before every spawn (`src/vaultspec_rag/qdrant_runtime/_spawn_trust.py`); the monitor launcher does not.

### Wording in accepted records that the wheel-pin direction touches

- `2026-09-11-binary-release-bundles-adr` Constraints: "The binary build must consume a version-checked wheel built from the release source (or an equivalent same-run artifact handoff), so binary contents do not depend on a race with PyPI publication."
- `.github/workflows/binaries.yml:497-498`: raw target-qualified executables remain private build intermediates.
- `2026-10-02-monitor-lifecycle-adr` Constraints: "Package installation and verified binary acquisition belong to delivery; this launcher performs no download or provisioning." It also resolves the installed command on PATH.
- `2026-10-09-automatic-merge-gate-autonomous-release-adr`: release-product provenance is attestation-based, executable hashes come from the authenticated archive, and reviewed committed pins remain required for toolchain binaries.
- `2026-10-05-qdrant-provisioning-trust-adr` removed Qdrant's PATH tier because automatic provisioning leaves no unprovisioned state for it to serve and it could resolve from the working directory on Windows.
