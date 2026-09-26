"""The one boolean vocabulary, and the one rejection shape, for env values.

A flag whose accepted words differ from its neighbour's is a flag operators
get wrong. ``off`` disabled one switch here while enabling another, and both
spellings looked equally reasonable in a shell. The table therefore lives in
exactly one place - and that place is now the framework, not this package, so
the same word in the same variable means the same thing across every vaultspec
tool rather than merely across this one.

This module is the package-local name for it, kept so the readers that grew up
against these names keep working, and kept deliberately thin: it adds no
behaviour, and there is nothing here for the framework's rules to drift from.

What a call site still owns is the *out-of-band* policy: what to do with a
blank value and with a word that spells neither state. :func:`parse_bool`
answers only the question it can answer everywhere - which state a recognised
word names - and returns ``None`` for anything else, so a reader that must
reject, one that must fail safe, and one that must defer to another library's
parser can each do so without a second copy of the table. Blank is not in
either table: it is unset, which :func:`is_blank` is for, and a reader decides
for itself whether unset means its default or its protective state.

The chain stays cheap on purpose. It is imported at module scope by code
reachable from spawn workers, which re-import their whole chain per worker,
and the framework module behind it imports nothing beyond the standard
library. Pulling the settings package (and through it the framework's
configuration package) or torch in here would reintroduce that cost in every
worker.
"""

from __future__ import annotations

from vaultspec_core.env_values import (
    BOOL_SHAPE as BOOL_SHAPE,
)
from vaultspec_core.env_values import (
    FALSE_TOKENS as FALSE_TOKENS,
)
from vaultspec_core.env_values import (
    TRUE_TOKENS as TRUE_TOKENS,
)
from vaultspec_core.env_values import (
    is_blank as is_blank,
)
from vaultspec_core.env_values import (
    parse_bool as parse_bool,
)
from vaultspec_core.env_values import (
    rejection as rejection,
)

__all__ = [
    "BOOL_SHAPE",
    "FALSE_TOKENS",
    "TRUE_TOKENS",
    "is_blank",
    "parse_bool",
    "rejection",
]
