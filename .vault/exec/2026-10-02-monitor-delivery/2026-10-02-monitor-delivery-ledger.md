---
tags:
  - '#exec'
  - '#monitor-delivery'
date: '2026-10-02'
modified: '2026-10-02'
body_schema: 'body-v2'
body_hash: 'sha256:2685cad5a1a6ec36f7301989cbab536dd65c84d25695b86fbb2089fb0db9ed50'
related:
  - "[[2026-10-02-monitor-delivery-plan]]"
---

<!-- Machine-owned, whole file: `vaultspec-core vault exec log` creates it
     on first use and appends every row; never hand-edit it. Add no
     frontmatter fields. Wiki-links belong in `related:` only.

     ONE ledger per plan, the only execution artifact. Each row's first
     column names its Step. -->

# `monitor-delivery` ledger

## Changes

<!-- MECHANICAL LOG, append-only, one row per path touched per Step, written
     by `--row`:
       - `S##` `A` `path`   added
       - `S##` `M` `path`   modified
       - `S##` `D` `path`   deleted
       - `S##` `R` `old` -> `new`   renamed
     Paths are repo-relative, in backticks. No prose: the Step row states the
     intent and the commit carries the diff.

     Optional per-Step rows, written by `--verify` and `--by`:
       - `S##` `verify:` `<command>` -> `pass` | `fail`
       - `S##` `by:` `<persona>`

     Rows are appended in Step order and never rewritten. Only rows in this
     section register a Step as covered. `--note` adds a `## Notes` section
     ONLY on exception (data loss, skipped work, a scaffold left in code, a
     persistent failure), one `S##`-prefixed line each; it is otherwise
     omitted. -->

- `S07` `A` `tools/binaries/bun_pins.py`
- `S07` `M` `.vault/adr/2026-10-02-monitor-delivery-adr.md`
- `S07` `M` `.vault/plan/2026-10-02-monitor-delivery-plan.md`
- `S07` `verify:` `ruff check bun_pins.py` -> `pass`
- `S07` `verify:` `ruff format --check bun_pins.py` -> `pass`
- `S07` `verify:` `ty check bun_pins.py` -> `pass`
- `S07` `verify:` `mdformat --check approval records` -> `pass`
- `S07` `verify:` `pymarkdown --config .pymarkdown.json approval records` -> `pass`
- `S07` `verify:` `vault plan check` -> `pass`
- `S07` `verify:` `vault check all --feature monitor-delivery` -> `fail`
- `S08` `M` `tools/binaries/bun_pins.py`
- `S08` `verify:` `ruff check bun_pins.py` -> `pass`
- `S08` `verify:` `ruff format --check bun_pins.py` -> `pass`
- `S08` `verify:` `ty check bun_pins.py` -> `pass`
- `S08` `verify:` `four archive pins verified before member hashing` -> `pass`
- `S01` `M` `src/monitor/server/local-service.ts`
- `S01` `A` `src/monitor/server/vite-plugin.ts`
- `S01` `M` `vite.config.ts`
- `S01` `M` `src/vaultspec_rag/monitor_inventory.py`
- `S01` `M` `src/vaultspec_rag/cli/__init__.py`
- `S01` `A` `src/vaultspec_rag/cli/_service_inventory.py`
- `S01` `M` `src/vaultspec_rag/qdrant_runtime/_provision.py`
- `S01` `A` `tools/binaries/bun_toolchain.py`
- `S01` `A` `tools/binaries/native.py`
- `S01` `M` `tools/binaries/build_pyapp.py`
- `S01` `A` `tools/binaries/tests/test_bun_toolchain.py`
- `S01` `M` `.vault/adr/2026-09-11-binary-release-bundles-adr.md`
- `S01` `M` `.vault/adr/2026-09-30-monitor-browser-adr.md`
- `S01` `M` `.vault/adr/2026-09-30-monitor-tooling-adr.md`
- `S01` `M` `.vault/plan/2026-10-02-monitor-delivery-plan.md`
- `S01` `verify:` `Ruff lint and format affected Python` -> `pass`
- `S01` `verify:` `ty affected Python` -> `pass`
- `S01` `verify:` `basedpyright affected source` -> `pass`
- `S01` `verify:` `npm lint/typecheck/format checks` -> `pass`
- `S01` `verify:` `covering binary/bridge/inventory/Qdrant/progress tests 163 passed` -> `pass`
- `S01` `verify:` `inventory tests after final adapter type fix 8 passed` -> `pass`
- `S01` `verify:` `native Windows Bun provision and pinned version 1.4.2` -> `pass`
- `S01` `verify:` `pin-table/archive/executable/ambiguous-member guard mutation failure then restored pass` -> `pass`
- `S01` `verify:` `Markdown lint and format accepted ADR amendments` -> `pass`
- `S02` `M` `.vault/plan/2026-10-02-monitor-delivery-plan.md`
- `S02` `M` `dev/monitor-browser.mjs`
- `S02` `M` `justfile`
- `S02` `M` `src/monitor/index.html`
- `S02` `A` `src/monitor/server/standalone.ts`
- `S02` `M` `src/vaultspec_rag/qdrant_runtime/_provision.py`
- `S02` `M` `tools/binaries/build_pyapp.py`
- `S02` `M` `tools/binaries/bun_toolchain.py`
- `S02` `M` `tools/binaries/tests/test_build_pyapp.py`
- `S02` `M` `tools/binaries/tests/test_bun_toolchain.py`
- `S02` `M` `tools/binaries/tests/test_windows_icon.py`
- `S02` `M` `tools/binaries/windows_icon.py`
- `S02` `M` `tools/packaging/products.py`
- `S02` `A` `tools/monitor/__init__.py`
- `S02` `A` `tools/monitor/build.py`
- `S02` `A` `tools/monitor/frontend.py`
- `S02` `A` `tools/monitor/smoke.py`
- `S02` `A` `tools/monitor/entitlements.plist`
- `S02` `A` `tools/monitor/tests/__init__.py`
- `S02` `A` `tools/monitor/tests/test_frontend.py`
- `S02` `A` `tools/monitor/tests/test_build.py`
- `S02` `verify:` `ruff lint=pass; ruff format=pass; ty affected tools=pass; basedpyright provision=pass; npm lint/typecheck/format=pass; driver prettier=pass; binary+monitor tests=85pass1platformskip; source browser=11pass after favicon fix; native Windows Chrome smoke=pass94assets; four guard mutation-restore proofs` -> `pass`

## Notes

- `S07` Isolated worktree awaits the lifecycle session commit. The only vault findings are two dangling related links to its uncommitted ADR; these preparatory toolchain pin Steps do not depend on lifecycle implementation. GitHub bun-v1.4.2 release asset metadata supplied authoring digests, never runtime trust. No archives extracted or binaries executed.
- `S08` Authoring downloaded over the canonical HTTPS host-pinned transport, matched all archive constants committed by a12e589a, then hashed each unique Bun member in memory. No Bun execution. Lifecycle-related vault links remain pending its owner commit.
- `S01` One pre-existing platform-specific binary test skipped on Windows. The runtime trust path reuses the canonical HTTPS downloader, hash and flattening extractor rather than copying them. Guard proof: changed the Windows archive-table key, bypassed the archive digest comparison, bypassed the executable comparison, and admitted duplicate matches, respectively; each failed its named test on AssertionError or DID NOT RAISE, then passed after immediate byte-for-byte restoration. Source/managed runtime and native lifecycle integration belong to S02; pending lifecycle ADR links remain the sole known vault findings until that owner commit is merged.
- `S02` Windows finalized development artifact SHA256 27e898521f9b0f7d2726e340fb1258422814e388b0828e4df78df862058ca6d6, producer 45e29066598648dcebc1de1c309e77aa05e584fa, lock 40f681cafee2f79e3d47480e04dcc87adc569ac1ec64424976f95a7e12257a2a, Bun1.4.2. Version/render/all94asset hashes+MIME+CSS/fonts, PATH-empty isolated home, unavailable backend, ignored dotenv/bunfig, foreign-origin denial, strict port refusal, managed upward allocation and EOF shutdown passed. Browser denies remote origins; OS-level egress denial not claimed. Actual in-flight canonical MonitorProcess source SHA256 ea26ac35b9b4f0b48d523ce991afe513b9a1f7d277db7296ffa103a3ba718c83 interoperated with finalized older prototype dca11fe3bcbb782c63bd0478fed823488dd054270a4d657abf4260fd58de78c7: initialized Python override served stopped lifecycle/persisted inventory then identity cleanup. Owner commit/merge pending S09; Linux/mac native evidence pending S04/S06. Guards bypassed shared executable hash, handoff comparison, dirty producer check and eagerly imported service config: intended assertions failed, originals restored and passed. Proof at temp monitor-delivery-records/s02-guard-proofs.json. One failed-probe temporary directory cleanup rejected by automatic policy; no retry bypass.
