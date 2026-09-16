"""Cancel-safe sleep for every Textual timer the jobs interface runs.

On Windows Textual sleeps its timers by parking a default-executor thread in
an unbounded wait on a waitable timer plus a cancel event. When a timer task
is cancelled twice in quick succession - ``Timer._stop_all`` cancels the
timer and awaits it, and that awaiter is itself cancelled during app or loop
teardown - the second cancellation discards the queued call that would set
the cancel event, and the handles are closed underneath the parked thread.
That thread never returns, and closing the event loop then blocks for the
full default-executor shutdown timeout (five minutes) before giving up.

Timers here drive polls and repaints measured in seconds, so the sub-tick
precision the Windows path buys is worth nothing, and an event-loop sleep has
no thread to strand. ``textual.timer`` resolves ``sleep`` as a module global
on every tick, so rebinding it covers every timer, including the ones Textual
starts internally.
"""

from __future__ import annotations

import asyncio

import textual.timer

__all__ = ["install_cancel_safe_timer_sleep"]

# asyncio overshoots a requested sleep by roughly half a millisecond; Textual
# trims the same amount on its event-loop path.
_SLEEP_OVERHEAD_SECONDS = 0.0005


async def _cancel_safe_sleep(secs: float) -> None:
    """Sleep on the event loop, leaving nothing behind when cancelled."""
    sleep_for = secs - _SLEEP_OVERHEAD_SECONDS
    if sleep_for > 0:
        await asyncio.sleep(sleep_for)


def install_cancel_safe_timer_sleep() -> None:
    """Make every Textual timer sleep on the event loop. Idempotent."""
    # Written through the module namespace: the attribute is typed as Textual's
    # own platform sleep, and this replaces it with an equivalent signature.
    vars(textual.timer)["sleep"] = _cancel_safe_sleep
