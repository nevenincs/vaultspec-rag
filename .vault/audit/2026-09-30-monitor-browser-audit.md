---
tags:
  - '#audit'
  - '#monitor-browser'
date: '2026-09-30'
modified: '2026-09-30'
body_schema: 'body-v2'
body_hash: 'sha256:cd4362d0447328cceba4fd57a8d56fc577d9a2fa1f5d7dcfbf47586c3ef76646'
related:
  - "[[2026-09-30-monitor-browser-plan]]"
  - "[[2026-09-30-monitor-browser-adr]]"
  - "[[2026-09-30-monitor-tooling-adr]]"
  - "[[2026-09-30-monitor-refinement-audit]]"
  - "[[2026-07-29-server-watch-observability-adr]]"
  - "[[2026-06-11-service-jobs-operability-adr]]"
  - "[[2026-07-21-managed-log-contract-adr]]"
  - "[[2026-09-21-typesafe-classifier-adr]]"
---

# `monitor-browser` audit: `Integrated local Carbon operator monitor review`

## Scope

Review completed S01/S02 in 2026-09-30-monitor-browser-plan. Diff base: 39c0365f, the completed TUI checkpoint; target: 06498161 and 642eff14 plus final working-tree refinements and documentation. The preceding TUI audit is PASS with 162 covering tests and remains applicable. Decisions: monitor-browser, monitor-tooling, server-watch-observability, service-jobs-operability, managed-log-contract and typesafe-classifier.

Trace automatic local discovery through the server-only bridge, production HTTP owners, browser validation and independent observers, Carbon presentation, scoped log readers and selected-job actions. Verify local access without credential or admin UI, bounded retained lifecycle views, TypeSafe evidence, diagnostic units, source/identity separation, failure retention, cancellation, responsive layout and exact service-owned controls.

Verification owner is the solo executor/reviewer. Windows, Python 3.13.14, Node 26.10.0/npm 12.1.0, pinned Carbon React 1.117.0 and Sass 1.105.1; real production routes, ledgers, managed files and installed headless Chrome. No resident daemon lifespan, inference, provider call, GPU workload or index recovery was run.

## Findings

### integrated-monitor | low | Both waves satisfy the operator scope

PASS. The local browser discovers the service and resolves its existing credential internally, without returning that credential or presenting a login/admin gate. Forwarding is limited to loopback monitor reads and exact job actions. Reads and action bodies have time and byte bounds. Browser observations validate identities, log scopes and service bounds, cancel previous owners and preserve earlier evidence after failures.

Health and TypeSafe remain separate from indexing state. Indexing and serving views show service-owned queued, processing and retained finished work, with honest missing values and snapshot counts. Inspectors update by stable identity and show metadata freshness separately from log freshness. Job and request logs stay correlated; raw service and Qdrant logs remain separate. Diagnostic milliseconds, seconds and counters keep their units. Buttons follow capabilities and revisions, requests have no job controls, and deleting a record requires confirmation.

Final production-route/model/rendered/log covering command: `uv run --no-sync pytest -m unit src/vaultspec_rag/tests/test_monitor_browser.py src/vaultspec_rag/tests/test_monitor_browser_render.py src/vaultspec_rag/tests/test_monitor_logs.py`: 12 passed in 179.76s, exit 0; evidence `.pytest-tmp/monitor-browser-covering-final.log`. Rendered coverage includes 1440x1000, 800x900 and 390x844, live logs without reselection, exact scope changes, retained evidence/reconnection, polling pause/resume, inert HTML, units, and deletion of the current terminal job. Visual artifacts at `.pytest-tmp/carbon-monitor-{1440,800,390}.png` were reviewed.

`just check-monitor` passed lint, formatting, strict TypeScript and production build; `npm run build` also passed. Package Ruff, changed-test format, ty and basedpyright passed. Explicit helper Prettier, workflow, canonical devserver, Markdown and focused guide formatting checks passed. Log paths are recorded in the execution ledger. No critical or high finding remains.

### guards | low | Regression assertions were proven against deliberate failures

Scope/duplicate-identity validation, wrong work-log scope, request job controls, lost evidence on failure, polling during pause, log HTML rendering, obsolete table rows and capability-disabled buttons each failed the intended assertion when their production guard was broken, then passed after restoration. Uninterrupted mutation/restoration evidence is in `.pytest-tmp/browser-projection-*` and `.pytest-tmp/browser-render-*`; comments beside the tests identify the mutations.

The deletion check exposed Carbon's temporary old rows after a new projection. Skipping an absent row before dereferencing its record prevents a blank monitor, and the inspector reports when selected work leaves its bounded page. The removed-row mutation reproduced the defect and restoration passed.

### carbon-layout | low | Automated notices were checked against rendered behavior

Carbon MCP audited seven components/styles with zero errors, two warnings and one informational notice. The shell warning cannot see the companion `monitor-content` spacing token; rendered checks confirm heading clearance below the fixed header. The feature tile intentionally spans a full second row at medium width and four of sixteen columns at large width; all breakpoints and row gaps are explicit and the medium screenshot confirms the layout. The modal notice recommends composed-modal slots, while the implementation uses the official standard Modal API with heading, description and buttons. Retain that standard API.

Official package styles, IBM Plex, Grid/Column/Stack, status indicators, tables, tabs and notifications are used. Custom SCSS uses Carbon tokens without internal component selector overrides or inline styles. Build warnings are upstream Carbon Sass deprecations and did not prevent the pinned production build.

### rendered-environment | low | Installed-browser checks are explicit about availability

All four rendered cases ran locally and passed. The fixture uses an already installed Chrome/Chromium/Edge, isolated profile and owned process; it downloads no browser and skips with an explicit reason if browser infrastructure is absent. Existing correctness workflows enroll Node and install monitor dependencies. A future CI environment without an installed browser will still run bridge/model checks but must supply that browser to run rendered cases.

## Recommendations

Final verdict: PASS. The two-wave implementation and final corrections are reviewable on the feature branch. Use the source-checkout instructions in `docs/service-mode.md`; the normal local service must already be started through its existing lifecycle. Development and built preview both include the automatic local adapter. Standalone static assets do not provide it. Continue to show bounded retained work rather than implying an all-time archive; remote deployment or new service authority requires the decision assessment stated in monitor-browser.
