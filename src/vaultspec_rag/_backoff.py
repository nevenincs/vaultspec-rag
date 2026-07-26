"""How long to wait before the next attempt, computed in one place.

Five sites grew their own capped exponential: the file-replacement retry
ladder, the watcher's retry policy, and three copies inside the watcher's
replacement scheduler. The arithmetic is small, which is exactly why it was
rewritten rather than shared - and small arithmetic is where an off-by-one or
a missing clamp survives review.

They had already diverged in a way that mattered. ``2 ** (streak - 1)`` builds
an integer before it is multiplied by a float, so a streak past 1024 raises
``OverflowError`` rather than returning the cap. The watcher's retry policy
clamped the exponent against exactly that; the three copies in the replacement
scheduler did not, and a root whose replacement keeps failing reaches the
overflow after about eight and a half hours at the thirty-second cap. One
copy knew; the others were written from the same idea and missed it.

The cap is honoured on the way out as well as on the way in. Jitter is applied
to a nominal that is already capped, so a positive draw could otherwise push
the wait past the maximum the caller asked for.
"""

from __future__ import annotations

__all__ = ["capped_exponential", "jittered_backoff"]

#: Exponent ceiling. ``2.0 ** 62`` is about 4.6e18, so any base a caller could
#: sensibly pass is already far past its cap by then and the result is the cap
#: either way. Clamping here is what keeps a long failure streak returning the
#: cap instead of raising: both ``2 ** n`` and ``2.0 ** n`` overflow well
#: before a streak that a long-lived daemon cannot reach.
_MAX_EXPONENT = 62


def capped_exponential(exponent: int, *, base: float, cap: float) -> float:
    """Return ``base * 2**exponent``, never above *cap* and never overflowing.

    The exponent is passed rather than an attempt or streak count, because the
    callers disagree about which is which: a retry ladder numbers its attempts
    from zero and a failure streak counts from one. Naming the exponent leaves
    that offset visible at the call site instead of hidden in here, where the
    wrong reading would be indistinguishable from the right one.
    """
    return min(base * (2.0 ** min(exponent, _MAX_EXPONENT)), cap)


def jittered_backoff(
    exponent: int,
    *,
    base: float,
    cap: float,
    fraction: float,
    random_unit: float,
) -> float:
    """Return a capped exponential wait spread by +/- *fraction*.

    Jitter decorrelates one waiter's retries from whatever it is contending
    with, so repeated collisions do not lock-step. *random_unit* is supplied by
    the caller rather than drawn here: one caller wants a real draw and the
    other pins it to make the ladder assertable, and a function that reached
    for the global generator would deny the second.

    The result is clamped to *cap* on both sides - never negative, and never
    above the maximum the caller set, which an unclamped positive draw would
    exceed by *fraction*.
    """
    nominal = capped_exponential(exponent, base=base, cap=cap)
    jitter = nominal * fraction * ((2.0 * random_unit) - 1.0)
    return min(cap, max(0.0, nominal + jitter))
