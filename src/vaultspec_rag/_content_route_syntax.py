"""What makes a content-route pattern well formed, stated once.

A caller-authored route crosses two shapes: the configuration boundary parses
it with its raw target token still a string, and policy compilation turns that
into the closed-vocabulary form the indexer uses. Each shape validated the
pattern for itself, with the same two rules and the same two sentences.

They had not drifted, and the cost of that is entirely in the future: the two
run at different layers, so a rule added to one and not the other does not
disagree loudly. It accepts a route at the boundary that compilation later
rejects, or the reverse - and which error an operator sees depends on how far
their configuration got before the missing check would have fired.

Stdlib only, and deliberately its own module rather than a home in either
side: configuration must not import the indexer, and the policy vocabulary
advertises itself as a dependency-free boundary, so neither could host the
rule without one of them taking on the other.
"""

from __future__ import annotations

__all__ = ["validate_content_route_pattern"]


def validate_content_route_pattern(pattern: str) -> None:
    """Require a non-empty, NUL-free content-route pattern.

    Args:
        pattern: The caller-authored project-relative match pattern.

    Raises:
        ValueError: When *pattern* is blank or carries an interior NUL. A NUL
            is rejected rather than stripped because the pattern reaches
            filesystem matching, where a truncating consumer would silently
            match a shorter path than the one written.
    """
    if not pattern.strip():
        raise ValueError("content route pattern must not be empty")
    if "\0" in pattern:
        raise ValueError("content route pattern must not contain NUL")
