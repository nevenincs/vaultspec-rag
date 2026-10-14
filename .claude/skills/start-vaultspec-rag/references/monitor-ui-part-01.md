# Local monitor UI and bridge: evidence group s1-0015

Read this part when working with: [patches/@carbon+charts-react+1.27.20.patch](../../../../patches/%40carbon%2Bcharts-react%2B1.27.20.patch), [patches/README.md](../../../../patches/README.md).

This is static evidence. Implementation observations, documentation claims, and test expectations remain distinct; no tests were run. An imported dependency uninspected within this evidence group may be covered in another capability reference. All listed full-file ranges are covered; report-local dependency boundaries are not inventory gaps.

[Local monitor UI and bridge](monitor-ui.md) provides module summaries, connections, and reconciled limitations.

## Capability summary

- The patch changes the installed ESM bundle `node_modules/@carbon/charts-react/dist/index.mjs` (diff target, line 1). Its DOM utilities retain the fullscreen handler, `ResizeObserver`, and resize callback so destruction can remove the listener, disconnect observation, and cancel pending resize work (patch lines 7-19, 22-25). The callback compares holder dimensions and dispatches a chart resize event when they change (patch lines 22-25).
- DOM utility destruction is called from chart destruction before chart components are destroyed and the holder is removed (patch lines 33-37). The status indicator keeps the `status-indicator` selector class when its status is null, as well as adding a status-specific class when present (patch lines 27-30).
- The React wrapper appends a child `div` to its host and creates the chart in that child; on unmount it destroys the chart and clears its reference (patch lines 39-54). This gives the chart an owned container while preserving the React host.
- [patches/README.md](../../../../patches/README.md) documents the patch's purpose, installation expectation, and reported browser checks and profiling (README lines 1-27). It names `test_chart_updates_and_navigation_release_browser_resources` and `test_background_monitor_stops_polling_and_resumes`; these are documentation claims only in this assignment, not inspected test modules or verified results.

## Interfaces and data flow

- The wrapper lifecycle uses `chartRef.current` as the React host, creates a child holder, then passes `this.props.data` and `this.props.options` to `createChart`. Its existing update path applies changed data and options through the chart model (patch lines 39-67).
- The chart's destroy path calls `services.domUtils.destroy()`, destroys components, removes the holder, and marks the model destroyed (patch lines 33-37). DOM cleanup uses instance fields `fullscreenListener`, `resizeObserver`, and `resizeListener` (patch lines 7-19, 22-25).
- Browser integrations shown are `document` fullscreen events and `ResizeObserver`; resize changes are forwarded through the chart event service (patch lines 7-13, 22-25). No persistent storage or network interface is shown in the assigned diff.

## Boundaries and dependencies

- The diff is scoped to the package's bundled ESM entry point. The README says the monitor imports `@carbon/charts-react` 1.27.20, that this entry point bundles Carbon Charts core, and that `npm ci` applies the pinned patch with `patch-package --error-on-fail`; it says the unused CommonJS entry point is not patched (README lines 1-15). These are documentation claims; package metadata and install configuration were not inspected.
- The patch calls internal `services.domUtils`, chart component/model APIs, and helper `Va`. Their definitions and the behavior of `.cancel()` were not inspected, so their implementation details are unknown. The browser regression test source and runtime are also uninspected.

## Evidence

- DOM utility listener/observer cleanup and resize dispatch wiring | `patches/@carbon+charts-react+1.27.20.patch:7-25` | implementation.
- Null-status selector retention | `patches/@carbon+charts-react+1.27.20.patch:27-30` | implementation.
- Chart destruction order and React mount/unmount lifecycle | `patches/@carbon+charts-react+1.27.20.patch:33-67` | implementation.
- Package version, ESM/CJS scope, patch application, claimed browser coverage, and profiling figures | [patches/README.md:1-27](../../../../patches/README.md#L1) | documentation claim.
- The named redraw/navigation test is said to check growth and detached resources, with separate failure assertions for selector repair and unmount cleanup; the background-monitor test is said to switch browser tabs and check request counts when the visibility gate is removed | [patches/README.md:20-27](../../../../patches/README.md#L20) | test expectation described by documentation, not inspected test code or a passing test.
- The resize callback appears cancelable because the patch calls its `.cancel()` method; actual helper semantics are unverified | `patches/@carbon+charts-react+1.27.20.patch:22-25` | inference.

## Uncertainty and follow-up

- No gaps in assigned ranges. To verify claims beyond this static slice, inspect the actual browser test modules and package patch configuration; to establish cancellation semantics, inspect the definition of `Va` in the patched bundle. These files were intentionally not read.
