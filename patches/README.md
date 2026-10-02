# Carbon Charts lifecycle repair

The monitor imports the ESM entry point of `@carbon/charts-react` 1.27.20.
That entry point bundles its own Carbon Charts core. Its patch fixes:

- React unmount cleanup, including React StrictMode remounts. The imperative
  chart owns a child container, so destroying it preserves React's host element.
- Document fullscreen listeners, resize observers and pending resize callbacks
  surviving chart destruction.
- Meter redraws appending empty SVG groups after removing their selector class.

`npm ci` applies the pinned patch through `patch-package --error-on-fail`.
The browser regression tests exercise the installed production entry point.
Recheck these cases before updating Carbon Charts or removing the patch.
The unused CommonJS entry point is not patched.

Profiling with Chrome's DOM counters after garbage collection found 4,068 extra
nodes and 774 extra listeners after six Storage revisits. With the patch, all
six revisits retained the same 859 nodes and 318 listeners. A 30-second live
dashboard sample previously added 200 nodes; its node count now remains flat.

`test_chart_updates_and_navigation_release_browser_resources` checks redraw
growth and detached resources. Removing the SVG selector repair fails its
node-growth assertion; removing unmount cleanup fails its retained-node
assertion. Both mutations were checked independently and restored.
`test_background_monitor_stops_polling_and_resumes` switches actual browser
tabs; removing the visibility gate fails its request-count assertion.
