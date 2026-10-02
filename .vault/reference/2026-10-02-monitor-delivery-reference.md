---
tags:
  - '#reference'
  - '#monitor-delivery'
date: '2026-10-02'
modified: '2026-10-02'
body_schema: 'body-v2'
body_hash: 'sha256:ef45b9763f378b2c2656856b48dbeb6ec47de2deeccfefa6f1db3c0b8cb5cd5b'
related:
  - "[[2026-09-30-monitor-browser-adr]]"
  - "[[2026-09-30-monitor-tooling-adr]]"
  - "[[2026-09-11-binary-release-bundles-adr]]"
  - "[[2026-09-30-release-standard-reference]]"
---

# `monitor-delivery` reference: `Current monitor build and RAG delivery seams`

Reviewed `feature/monitor` at commit `1cb008754d9ecd05e04d255646647a5d3907a6ba` on 2026-10-02. Semantic discovery was available after service warm-up but reported unverifiable freshness; full ADR enumeration and direct source reads establish the findings below. Earlier bundle references describe historical behavior; this record describes the checked-out implementation.

## Summary

### The frontend build ends at static assets

`package.json:44` runs strict TypeScript followed by Vite, with npm and `package-lock.json` as the dependency authority. The root package is private and its version is `0.0.0`, so it provides no published bunx package or release identity (`package.json:2`). The reviewed patch-package postinstall also belongs to dependency restoration. `vite.config.ts:9` roots Vite at `src/monitor`, uses relative asset URLs, and produces `src/monitor/dist`. `justfile:118` exposes that build; `dev/toolchain.py:342` runs frontend lint, format, type and build gates. There is no standalone monitor executable entry point in the listed frontend server module.

### Vite owns the only current server adapter

`src/monitor/server/local-service.ts:497` registers the same middleware in Vite dev and preview. `:52` checks the socket peer, Host and matching Origin; `:175` restricts operations; `:207` recursively removes credentials. `:389` bounds requests with cancellation and path-specific deadlines. `:440` targets the discovered local service and retries authentication through health recovery. A production adapter must preserve these behaviors through one shared implementation. The binding and tailnet policy are settled by `2026-09-30-monitor-browser-adr`; the shared devserver harness is settled by `2026-09-30-monitor-tooling-adr`.

### Service controls depend on the checkout rather than a portable installation

`src/monitor/server/local-service.ts:14` derives a checkout directory from the source URL. `:234` resolves Python from uv tools or the checkout's `.venv`; `:269` spawns Python with that checkout as cwd and its `src` directory as PYTHONPATH. Lifecycle calls use the canonical Python CLI (`:312`), while stopped-service inventory invokes a module (`:331`). Compiling this module without changing that launch contract would leave filesystem and Python assumptions inside the executable.

`src/vaultspec_rag/monitor_inventory.py:14` already reuses canonical service projections for persisted repository/storage evidence. `:55` owns the bounded module process interface. Production command exposure should reach this owner, rather than reimplementing inventory in TypeScript or copying the Python projections.

### Packaging has a usable archive boundary and a fixed executable set

`tools/packaging/products.py:145` declares only `vaultspec-rag` and `vaultspec-search-mcp`. `:164` currently supports Windows x64, Linux x64, Linux ARM64 and macOS ARM64. The four-target matrix agrees at `.github/workflows/binaries.yml:174`; older three-target descriptions are historical.

`tools/packaging/bundles.py:218` stages finalized members from the product declaration. `:251` creates a deterministic archive and verifies it before its sidecar digest is written. `:453` requires the exact member set, hashes, sizes and modes. The manifest currently models Python/PyApp runtime and GPU/network requirements at `:124` and `:133`, and validates those exact values at `:357`. A monitor member therefore needs explicit runtime/requirement metadata evolution, not just another executable name. `tools/binaries/build_pyapp.py:320` declares glibc 2.39 for both Linux targets; that remains the full RAG bundle floor even if the Bun member needs an older libc.

### Release order already separates safe build proof from public acquisition

The immutable source SHA and exact-wheel handoff are enforced in `.github/workflows/binaries.yml:206` and `:225`. Per-target build/bundle recipes run at `:246` and `:253`. The draft completeness verifier at `:445` proves package assets, every target archive and exact checksum coverage; only its successful handoff dispatches package publication. `2026-09-30-release-standard-reference` records the publication and channel sequence, governed by `2026-09-30-release-standard-adr`.

`.github/workflows/acquisition.yml:94` downloads a public archive and live SHA256SUMS, verifies the selected archive entry and optionally its source revision. `:167` safely extracts the two named executable members. `:210` checks the Linux loader and declared libc floor; it deliberately launches no application. Its matrix at `:69` covers only Linux x64 and ARM64. The live checksum proves consistency with that release's metadata; it is not an independently reviewed artifact pin.

### Existing browser checks do not prove binary delivery

`src/vaultspec_rag/tests/test_monitor_browser.py:39` imports TypeScript middleware under installed Node. `src/vaultspec_rag/tests/test_monitor_browser_render.py:68` uses an installed browser and the checkout. Despite its production-render comment, `dev/monitor-browser.mjs:7` creates a Vite development server. These checks supply useful behavioral coverage but do not establish that packaged assets or a compiled server work without the source tree and toolchain. Delivered-binary launch and browser checks must supplement them.

### Concurrent managed lifecycle work defines the packaged launch seam

A separate session has added `src/vaultspec_rag/monitor_process.py` and `src/monitor/server/managed.ts` during this review; these are uncommitted observations, not part of the pinned source checkpoint above. The authored ruling in `2026-10-02-monitor-lifecycle-adr` records explicit user authorization for backend-coupled monitor start/stop, allocation above backend port plus one, and actual port/PID/incarnation discovery. Its source-only implementation excludes packaging.

`src/vaultspec_rag/monitor_process.py:135` currently launches Node plus a source Vite entry; `src/monitor/server/managed.ts:9` uses Vite upward port retries and `:23` shuts down on parent-pipe EOF. The supervisor owns readiness, scratch identity, rollback and forced-stop cleanup. Packaging must let this same owner select the installed monitor binary and preserve its readiness/EOF contract. A second supervisor or a fixed deployed monitor port would conflict with this work. Shared dev/preview manifest ports remain a separate development contract. The lifecycle record was still scaffolded with an authored accepted Context section when read; its owning session must finish canonical status/body normalization before dependent implementation.
