---
tags:
  - '#reference'
  - '#jobs-tui'
date: '2026-07-27'
modified: '2026-07-28'
related:
  - "[[2026-07-27-jobs-tui-adr]]"
  - "[[2026-07-27-jobs-tui-research]]"
---

# `jobs-tui` reference: `interrupt and terminal handoff`

What a real console interrupt does to the shipped owned-screen interface, measured
against a live child process on its own console rather than inferred from the code. The
record exists because the interface changed what an interrupt means on this command and
nothing in the feature's grounding described the new behaviour.

Every figure below was taken from a spawned CLI on a hidden console, interrupted by a
genuine `CTRL_C_EVENT` generated on that console by a separate short-lived process.

## Summary

### The interface absorbs the interrupt and returns normally

A console interrupt delivered while the view is running ends the process on status `0`,
with both streams free of a traceback and `stderr` empty. The interrupt is serviced by
the running event loop, which unwinds the application and returns through
`src/vaultspec_rag/cli/_jobs_tui.py:1350` as an ordinary return.

### The unwind is observable as terminal teardown, and it is what hands the screen back

The application takes the alternate screen buffer and hides the cursor on entry, and
gives both back on exit. Measured over one interrupted run, each sequence occurs exactly
once and in this order: enter alternate screen at the head of the stream, hide cursor
immediately after, then at the tail mouse reporting off, leave alternate screen, show
cursor. The teardown is emitted by the unwind, not by the interrupt.

This is the only externally observable evidence that the terminal was handed back. A
process that ends without unwinding emits the entry half and never the exit half, which
leaves the operator's shell on the alternate screen with the cursor still hidden - a
working shell that renders as a dead one.

### Without the interface, the same interrupt reports 130

With the live path parked in a plain wait after one refresh rather than handing the
screen to the interface, the identical interrupt ends the same command on `130`, with no
traceback. The status comes from the entry point's own startup guard
(`src/vaultspec_rag/__main__.py:29` and `src/vaultspec_rag/__main__.py:71`), which
catches an otherwise unhandled `KeyboardInterrupt` and reports the conventional
interrupted status.

The `0` is therefore a property of the interface absorbing the interrupt and returning,
not of the interrupt failing to arrive. Both numbers are reachable on this command
depending only on who handles the signal.

### A handler that exits without unwinding is indistinguishable by status alone

Exiting hard from a signal handler inside the interface produces status `0` and no
traceback - identical on both counts to the clean path - while emitting no teardown at
all. Status and stream cleanliness cannot separate the two cases; only the teardown
sequence can.

### The live path has no structured consumer

The live view is refused in combination with structured output at
`src/vaultspec_rag/cli/_service_jobs_watch.py:34`, so no caller can request this path and
parse an envelope from it. The command's documented exit line carries `0`, `2` for an
invalid filter, and `3` for a service that is not running.

### The rendered stream is not decodable as text

The interface paints escape sequences and box-drawing characters that the console's ANSI
codepage cannot decode. Capturing a child's output as text tears the reader thread down
on a decode error and yields a `None` stream rather than a diagnosable failure, so any
verification of this surface has to read the child as bytes. This bears directly on the
feature's established bar of verifying operator feedback on rendered bytes.

## Sources

- `src/vaultspec_rag/cli/_jobs_tui.py:1350` - the run entry the unwind returns through
- `src/vaultspec_rag/cli/_service_jobs_watch.py:34` - structured output refused on the
  live path
- `src/vaultspec_rag/cli/_service_jobs_watch.py:61` - the live path's handoff to the
  interface
- `src/vaultspec_rag/__main__.py:29` - the conventional interrupted status constant
- `src/vaultspec_rag/__main__.py:71` - the entry point's unhandled-interrupt guard
- `src/vaultspec_rag/tests/integration/test_cli_jobs_watch_console_interrupt.py` - the
  measurements above, as an executable guard
- `src/vaultspec_rag/tests/integration/_console_interrupt.py` - the console-event
  delivery harness the measurements were taken through
- `docs/cli.md:355` - the command's documented exit line
