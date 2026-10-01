---
tags:
  - '#audit'
  - '#monitor-operations'
date: '2026-10-01'
modified: '2026-10-01'
body_schema: 'body-v2'
body_hash: 'sha256:f00b50d8ed8b99b33ffd4cb4a5b59d31d2d517401b713e4f10a3a4ccf90e3d20'
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

### request-review | medium | Inline request review and stable expansion

S06 replaces the split tree/table panes with a single inline hierarchy. Expanded requests expose labeled summary values, query/input, progress/results, errors and related logs. Additional diagnostics remain expandable. Request expansion is controlled by request ID, nested expansion and sorting by field path, so polling does not reset user review state. Raw scalar values are preserved. Numeric sorting compares source values before formatting, including 145000 versus 150 and fractional scores. Storage chart labels use a project name or a Windows/Unix basename, while detail rows retain full paths.

### nested-layout | medium | Universal nested container reset

The Carbon expanded-row selector indented descendant cells and its table/accordion chevrons pointed down when collapsed and up when expanded. Scoped rules now map disclosure state to right/down and reset every expanded table cell/container to zero padding and margin. Normal table-cell spacing no longer inherits expanded-row indentation. Rendered checks cover nested rows, sorting and state retention. The original chevron assertion failed before the direction correction, then passed for desktop, mobile and nested rows.

### list-navigation | medium | Filter and sort before pagination

Canonical jobs and search activity owners now filter and sort before slicing bounded pages. Query projections preserve existing lanes and expose ordered records. Logs page within the bounded managed-log scan and combine exact request identity with text filtering. UI pagination, status/text filters and sorting use these routes. The page ceiling, negative-offset rejection and exact request-token guards were each deliberately broken, failed their named assertion, restored and passed.

### disk-inventory | medium | Service availability does not own persisted storage

Read-only fallback reuses canonical repository/manifest and filesystem inventory without opening Qdrant or loading GPU models. Missing live seats, watcher readings and point counts remain null; unavailable disk storage returns an error rather than fabricated zero inventory. Mutation proofs detect writes and torch imports. On the actual machine, the stopped service still exposed 58 saved repositories and 20 disk storage entries. After restart the service reported ready, and live paginated jobs/logs returned offset 10 with ten records.

### carbon-inline-tables | low | Composition audit reviewed against supplied examples

The static Carbon audit requires a DataTable state wrapper around every Table component. Carbon MCP itself supplies standalone Table examples; this implementation uses those public table building blocks with controlled expansion and sorting to retain state across polls. Native TableHeader sort buttons provide keyboard interaction. Browser checks validate the actual interaction and nesting.

## Recommendations

PASS for the implemented operations scope at backend 1f970999 and frontend ebed4441. No unresolved critical or high findings. Backend suite: 124 passed without skips. Installed-browser suite: 5 passed at 1440/800/390 widths, including nested returned results, invalid enrollment, scoped logs, retained evidence, live updates and exact selected-record deletion. Frontend lint/format/types/build and changed Python lint/format/ty/basedpyright pass. Backend guard mutation proofs and the persistent-sidebar fail/restore proof are recorded in the ledger and local check logs.

The production build reports upstream Carbon Sass deprecations and a bundle-size advisory; it succeeds. Keep the live-validation limitation explicit: resident service start/stop and loaded GPU telemetry were not exercised. Storage management exposes survey refresh and canonical resident-seat release; destructive storage deletion remains outside the accepted HTTP surface. The prior external tailnet rollout is independent and remains open.

S05 follow-up: rendered suite passes all seven cases at 1440/800/390/320 widths, including the adjacent header actions, theme cycling, collapsible navigation, stopped-service display and dark notification styling. Bridge suite passes fourteen tests. The earlier operations verification remains historical evidence; the S05 ledger records the updated shell checks and deliberately failing layout guard.

S06 PASS: all eight installed-browser cases pass (142.96s), including 1440/800/390/320 layouts, live request/nested expansion retention, direct returned-result review, 145000 versus 150 ordering, zero nested wrapper spacing, request filtering/pagination and older log pages. Final monitor bridge/numeric projection suite: 14 passed. Backend pagination and persisted-inventory regression suites passed as recorded in the ledger. Lint, format, types, production build and feature vault checks pass. The actual service was idle before restart, persisted repository/storage inventory remained available while stopped, and the restarted service reported ready with new live pagination routes. Log history remains bounded by the managed-log scan, and offline point counts are explicitly unavailable.
