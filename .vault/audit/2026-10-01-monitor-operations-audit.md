---
tags:
  - '#audit'
  - '#monitor-operations'
date: '2026-10-01'
modified: '2026-10-01'
body_schema: 'body-v2'
body_hash: 'sha256:db7ee1e0512d1f63b37a33cc4a1b295c3b6e351ab3722b218fe5fb23ca043897'
related:
  - "[[2026-10-01-monitor-operations-plan]]"
---

# `monitor-operations` audit: Service operator interface

## Scope

Review S01 backend and S03 frontend against cf7c414b, including the working tree, under monitor-browser/tooling, quiesce, bounded observability and storage hygiene decisions. Principal owns frontend design and review; GPT-6.1 Sol high agents reviewed backend workflows.

## Findings

### resident-eviction | medium | Blocking eviction repaired

Synchronous resident eviction could stall unrelated routes. S01 validates the body and offloads the canonical owner to an AnyIO worker. A real root-lock concurrency test proves inventory responsiveness; replacing worker dispatch with inline execution fails the intended assertion and restoration passes.

### lifecycle-refresh | medium | Fresh health supersedes retained stopped state

S03 considers retained stopped lifecycle status only while health is absent or stale. Controls remain mounted across navigation to preserve pending actions.

### carbon-validation | low | Static audit contains syntax-related false positives

Carbon MCP supplied component examples and chart schemas. Static audit misidentifies the inline DataTable headers array as missing and flags the native Carbon HeaderMenuButton for keyboard handling. Required props are present and types pass. Installed-browser checks cover header clearance, persistent desktop navigation, mobile navigation and overflow at three widths.

### live-validation | low | Resident lifecycle and GPU compute remain unexercised

Production routes are exercised with real ledgers, temporary managed files, real sockets and the installed browser. Tests do not restart the user's resident daemon or load GPU models. Fixed lifecycle command boundaries and pause/resume routes have focused coverage. External tailnet rollout remains a separate monitor-browser step.

### relational-evidence | low | Nested results and enrollment error scope verified

The installed-browser interaction opens a real completed search response through its tree and nested result table, then submits an invalid relative enrollment path and checks the error inside the enrollment modal. Storage rows mark unverified point counts as lower bounds. The navigation guard was deliberately broken by disabling persistent SideNav; its desktop visibility assertion failed as intended before restoration.

### carbon-native-controls | low | Native Carbon controls satisfy keyboard behavior

The follow-up static audit also flags the native Carbon Button onClick and recommends ComposedModal children for the ordinary Modal API. Both usages follow the MCP component examples and installed APIs; extra keyboard listeners would duplicate native button behavior.

### mobile-capture | low | Wait for navigation close before screenshots

The final visual review caught screenshots taken during Carbon's sidebar close transition. S04 now waits for the sidebar to leave the viewport before capture. The two affected tablet/mobile cases pass again (39.85s); no product-code change was needed. Package lint and the changed test's format, ty and strict types pass.

### shell-controls | medium | Header, theme and navigation corrected after operator review

S05 uses Carbon HeaderGlobalAction with Renew immediately before the rightmost theme action. Awake, Asleep and Screen indicate persisted light/dark/system selection. Desktop and mobile navigation use the collapsible Carbon menu. Carbon Grid and mobile Accordion preserve separate pages and nested evidence. A neutral observation timestamp no longer duplicates health status. One service status derives from health or canonical lifecycle state, and stopped service hides retained live metrics. Low-contrast notifications follow the active theme. Carbon type reset supplies IBM Plex to inherited text.

### lifecycle-runtime | medium | Start uses the enrolled runtime

The bridge resolves the installed uv tool interpreter before the checkout environment and accepts canonical stopped status responses independently of the command's ok flag. Fourteen bridge tests pass. The interpreter preference mutation fails its assertion and passes after restoration. The resident daemon was not started by this verification.

### shell-verification | low | Rendered guards exposed real layout defects

Header containment failed before setting the global action bar to Carbon's 48px header height. Isolated browser Vite caches prevent tests from invalidating the operator's dev assets. Carbon static audit repeats the native HeaderMenuButton keyboard false positive: it renders a native button. Page-heading focus is a navigation focus target, not a trap. Final rendered checks are recorded in the execution ledger.

## Recommendations

PASS for the implemented operations scope at backend 1f970999 and frontend ebed4441. No unresolved critical or high findings. Backend suite: 124 passed without skips. Installed-browser suite: 5 passed at 1440/800/390 widths, including nested returned results, invalid enrollment, scoped logs, retained evidence, live updates and exact selected-record deletion. Frontend lint/format/types/build and changed Python lint/format/ty/basedpyright pass. Backend guard mutation proofs and the persistent-sidebar fail/restore proof are recorded in the ledger and local check logs.

The production build reports upstream Carbon Sass deprecations and a bundle-size advisory; it succeeds. Keep the live-validation limitation explicit: resident service start/stop and loaded GPU telemetry were not exercised. Storage management exposes survey refresh and canonical resident-seat release; destructive storage deletion remains outside the accepted HTTP surface. The prior external tailnet rollout is independent and remains open.

S05 follow-up: rendered suite passes all seven cases at 1440/800/390/320 widths, including the adjacent header actions, theme cycling, collapsible navigation, stopped-service display and dark notification styling. Bridge suite passes fourteen tests. The earlier operations verification remains historical evidence; the S05 ledger records the updated shell checks and deliberately failing layout guard.
