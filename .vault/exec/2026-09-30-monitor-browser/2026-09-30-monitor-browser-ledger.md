---
tags:
  - '#exec'
  - '#monitor-browser'
date: '2026-09-30'
modified: '2026-10-01'
body_schema: 'body-v2'
body_hash: 'sha256:49afb2eed96d6ef1aba1e318d285dcd5da3194b2990fbf79ad78048d3e28095b'
related:
  - "[[2026-09-30-monitor-browser-plan]]"
---

# `monitor-browser` ledger

## Changes

- `S01` `A` `src/monitor/server/local-service.ts`
- `S01` `M` `vite.config.ts`
- `S01` `M` `package.json`
- `S01` `M` `package-lock.json`
- `S01` `A` `src/vaultspec_rag/tests/test_monitor_browser.py`
- `S01` `M` `src/vaultspec_rag/tests/test_monitor_logs.py`
- `S01` `A` `.vault/adr/2026-09-30-monitor-browser-adr.md`
- `S01` `M` `.vault/adr/2026-09-30-monitor-tooling-adr.md`
- `S01` `A` `.vault/plan/2026-09-30-monitor-browser-plan.md`
- `S01` `verify:` `npm run lint` -> `pass`
- `S01` `verify:` `npm run format:check` -> `pass`
- `S01` `verify:` `npm run typecheck` -> `pass`
- `S01` `verify:` `npm run build` -> `pass`
- `S01` `verify:` `ruff check src/vaultspec_rag` -> `pass`
- `S01` `verify:` `ruff format --check changed Python tests` -> `pass`
- `S01` `verify:` `ty check changed Python tests` -> `pass`
- `S01` `verify:` `basedpyright changed Python tests` -> `pass`
- `S01` `verify:` `pytest unit browser bridge: 3 passed; .pytest-tmp/monitor-bridge-final.log` -> `pass`
- `S01` `verify:` `pytest unit monitor log fixture regression: 4 passed; .pytest-tmp/monitor-browser-adapter.log` -> `pass`
- `S01` `verify:` `token redaction, local origin and route scope guard mutations: assertion failed and restored passed` -> `pass`
- `S01` `M` `.github/workflows/merge-gate.yml`
- `S01` `verify:` `just check-workflow` -> `pass`
- `S01` `verify:` `vaultspec-core vault check all --feature monitor-browser --fix` -> `pass`
- `S01` `verify:` `vaultspec-core vault plan check monitor-browser` -> `pass`
- `S02` `A` `src/monitor/App.tsx`
- `S02` `A` `src/monitor/Health.tsx`
- `S02` `A` `src/monitor/Inspector.tsx`
- `S02` `A` `src/monitor/Logs.tsx`
- `S02` `A` `src/monitor/Work.tsx`
- `S02` `A` `src/monitor/main.tsx`
- `S02` `A` `src/monitor/model.ts`
- `S02` `A` `src/monitor/monitor.scss`
- `S02` `A` `src/monitor/presentation.tsx`
- `S02` `A` `src/monitor/use-polling.ts`
- `S02` `M` `src/monitor/index.html`
- `S02` `A` `dev/monitor-browser.mjs`
- `S02` `M` `src/vaultspec_rag/tests/test_monitor_browser.py`
- `S02` `A` `src/vaultspec_rag/tests/test_monitor_browser_render.py`
- `S02` `M` `.github/workflows/merge-gate.yml`
- `S02` `M` `docs/service-mode.md`
- `S02` `M` `.vault/plan/2026-09-30-monitor-browser-plan.md`
- `S02` `M` `.vault/audit/2026-09-30-monitor-refinement-audit.md`
- `S02` `verify:` `just check-monitor (lint, format, TypeScript, production build); .pytest-tmp/monitor-browser-frontend-final.log` -> `pass`
- `S02` `verify:` `npm run build; .pytest-tmp/monitor-browser-build-final.log` -> `pass`
- `S02` `verify:` `npx prettier --check dev/monitor-browser.mjs` -> `pass`
- `S02` `verify:` `ruff check src/vaultspec_rag; .pytest-tmp/monitor-browser-ruff-final.log` -> `pass`
- `S02` `verify:` `ruff format --check browser, rendered browser and monitor log tests` -> `pass`
- `S02` `verify:` `ty check browser, rendered browser and monitor log tests` -> `pass`
- `S02` `verify:` `basedpyright browser, rendered browser and monitor log tests: 0 errors` -> `pass`
- `S02` `verify:` `uv run --no-sync pytest -m unit test_monitor_browser.py test_monitor_browser_render.py test_monitor_logs.py: 12 passed in 179.76s; .pytest-tmp/monitor-browser-covering-final.log` -> `pass`
- `S02` `verify:` `scope and duplicate-identity mutations: intended assertion failed and restored passed; .pytest-tmp/browser-projection-{scope,identity}-{broken,restored}.log` -> `pass`
- `S02` `verify:` `work-scope, request-controls, retention, poll-pause, html-escaping, removed-row and capabilities mutations: intended assertion failed and restored passed; .pytest-tmp/browser-render-*-{broken,restored}.log` -> `pass`
- `S02` `verify:` `Carbon MCP code_audit seven files: no errors; two warnings and one informational finding manually reviewed against official components, SCSS and rendered layouts` -> `pass`
- `S02` `verify:` `visual review 1440x1000, 800x900 and 390x844; .pytest-tmp/carbon-monitor-{1440,800,390}.png` -> `pass`
- `S02` `verify:` `just check-workflow; .pytest-tmp/monitor-browser-workflow-final.log` -> `pass`
- `S02` `verify:` `just check-devserver; .pytest-tmp/monitor-browser-harness-final.log` -> `pass`
- `S02` `verify:` `just check-markdown; .pytest-tmp/monitor-browser-markdown-final.log` -> `pass`
- `S02` `verify:` `mdformat --check docs/service-mode.md` -> `pass`
- `S02` `verify:` `git diff --check` -> `pass`
- `S02` `A` `.vault/audit/2026-09-30-monitor-browser-audit.md`
- `S02` `verify:` `integrated monitor review from 39c0365f through final S01/S02 working tree: PASS, no critical or high findings` -> `pass`
- `S02` `verify:` `vaultspec-core vault check all --feature monitor-browser --fix: all checks clean` -> `pass`
- `S02` `verify:` `vaultspec-core vault check all --feature monitor-refinement --fix: all checks clean` -> `pass`
- `S02` `verify:` `vaultspec-core vault plan check monitor-browser: 2 of 2 Steps complete` -> `pass`
- `S03` `M` `package.json`
- `S03` `M` `src/monitor/server/local-service.ts`
- `S03` `M` `src/vaultspec_rag/tests/test_monitor_browser.py`
- `S03` `M` `docs/service-mode.md`
- `S03` `M` `.vault/adr/2026-09-30-monitor-browser-adr.md`
- `S03` `M` `.vault/adr/2026-09-30-monitor-tooling-adr.md`
- `S03` `M` `.vault/plan/2026-09-30-monitor-browser-plan.md`
- `S03` `verify:` `just check-monitor (lint, format, strict TypeScript, production build); .pytest-tmp/monitor-tailnet-frontend-final.log` -> `pass`
- `S03` `verify:` `package Ruff and changed browser-test format, ty and basedpyright` -> `pass`
- `S03` `verify:` `pytest unit browser adapter and shared devserver guards: 22 passed in 5.48s; .pytest-tmp/monitor-tailnet-contract-final.log` -> `pass`
- `S03` `verify:` `pytest rendered Carbon monitor: 4 passed in 65.78s; .pytest-tmp/monitor-tailnet-render-final.log` -> `pass`
- `S03` `verify:` `canonical owner lifecycle and contract tests: 6 passed in 10.59s; .pytest-tmp/monitor-tailnet-owner-lifecycle.log` -> `pass`
- `S03` `verify:` `real degraded HTTP health on owned process caused replacement and recovered health; .pytest-tmp/monitor-tailnet-degraded-proof.log` -> `pass`
- `S03` `verify:` `just dev ci conform, attach, attach, stop; .pytest-tmp/monitor-tailnet-lifecycle-final.log` -> `pass`
- `S03` `verify:` `just dev subsequently started and left running on strict 5420 with 0.0.0.0 host` -> `pass`
- `S03` `verify:` `just dev check and just check-workflow; canonical recipe/workflow and byte digest guards` -> `pass`
- `S03` `verify:` `Tailscale origin, undeclared host and real client-source mutations: intended assertion failed and restored passed; .pytest-tmp/tailnet-{origin,host,client}-{broken,restored}.log` -> `pass`
- `S03` `verify:` `live page at 100.84.254.21:5420, health at gw-workstation.taild36992.ts.net:5420 and local reverse proxy: 200 with no daemon credential exposed` -> `pass`
- `S03` `verify:` `Tailscale peer gw-server connectivity and existing private-interface Node firewall allowances` -> `pass`
- `S03` `M` `.vault/audit/2026-09-30-monitor-browser-audit.md`
- `S03` `verify:` `guide mdformat check` -> `pass`
- `S03` `verify:` `live process command --port 5420 --strictPort --host 0.0.0.0 and listening address 0.0.0.0 verified` -> `pass`
- `S03` `verify:` `vaultspec-core vault check all --feature monitor-browser --fix` -> `pass`
- `S03` `verify:` `vaultspec-core vault check all --feature monitor-tooling --fix` -> `pass`
- `S03` `verify:` `vaultspec-core vault plan check monitor-browser` -> `pass`
- `S03` `verify:` `just check-markdown; .pytest-tmp/monitor-tailnet-markdown-final.log` -> `pass`
- `S03` `verify:` `corrective review: software checks PASS, tailnet HTTPS rollout pending external Serve enablement` -> `pass`

## Notes

- `S03` HTTPS rollout remains pending. The devservers-derived tailscale serve command reports Serve is not enabled on the tailnet and waits for account enablement. Setup link was given through the user-input tool; direct Tailscale HTTP and the local reverse proxy already work. Keep S03 open until HTTPS mapping and reachability can be verified.
- `S03` Remote peer HTTP probing over SSH could not run because the existing client credential was refused; live interface-address probes, private-interface firewall allowances and real peer ping are applicable local network evidence.
