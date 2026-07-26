"""The one boolean vocabulary, and the one rejection shape, for env values.

A flag whose accepted words differ from its neighbour's is a flag operators
get wrong. ``off`` disabled one switch here while enabling another, and both
spellings looked equally reasonable in a shell. So the token table lives in
exactly one place and every switch reads it, rather than each call site
deciding for itself what ``off`` means.

What a call site still owns is the *out-of-band* policy: what to do with a
word that spells neither state. :func:`parse_bool` answers only the question
it can answer everywhere - which state a recognised word names - and returns
``None`` for anything else, so a reader that must reject, one that must fail
safe, and one that must defer to another library's parser can each do so
without a second copy of the table.

The module is stdlib-only, and must stay that way. It is imported at module
scope by code reachable from spawn workers, which re-import their whole chain;
pulling the settings package (and through it the vaultspec-core config
package) or torch in here would reintroduce that cost in every worker.
"""

from __future__ import annotations

#: Spellings that name the on state.
TRUE_TOKENS: frozenset[str] = frozenset({"1", "true", "yes", "on"})

#: Spellings that name the off state. The empty string is included because
#: ``VAR=`` is how a shell spells "not on", and off is the safe direction to
#: resolve it in. A reader for which off is *not* the safe direction handles
#: the empty case before calling :func:`parse_bool`.
FALSE_TOKENS: frozenset[str] = frozenset({"0", "false", "no", "off", ""})

#: The human phrase completing "<name> must be ...". Built from the tables so
#: the message can never list a spelling the parser does not accept. The empty
#: string is omitted: it has no spelling to print.
BOOL_SHAPE: str = "one of " + ", ".join(
    sorted(token for token in TRUE_TOKENS | FALSE_TOKENS if token)
)


def parse_bool(raw: str) -> bool | None:
    """Return the state *raw* names, or ``None`` when it names neither.

    Comparison is case-folded and stripped, so an operator's stray whitespace
    or capitalisation resolves rather than being refused.

    Args:
        raw: The raw environment value.

    Returns:
        ``True`` or ``False`` for a recognised spelling; ``None`` for a word
        that is in neither table, leaving the caller to apply its own policy.
    """
    token = raw.strip().lower()
    if token in TRUE_TOKENS:
        return True
    if token in FALSE_TOKENS:
        return False
    return None


def rejection(where: str, shape: str, value: object) -> ValueError:
    """Build the one rejection message shape this project emits for env values.

    Args:
        where: What failed, named the way its reader identifies it - a bare
            variable name, or a variable name with the settings key it feeds.
        shape: The human phrase describing what was expected.
        value: The offending value, rendered for the operator.

    Returns:
        A ``ValueError`` naming the source, the value and the expected shape,
        so the message alone is enough to fix the mistake.
    """
    return ValueError(f"{where} must be {shape}, got {value!r}")
