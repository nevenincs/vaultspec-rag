"""Query parsing: extract metadata filter tokens from raw queries.

Splits a raw query string into a :class:`ParsedQuery` - the cleaned
natural-language text plus the structured filters lifted from tokens
like ``type:adr``, ``feature:rag``, or ``tag:#research``. Holds the
filter-token regex and the token-to-payload-key mapping.
"""

from __future__ import annotations

import re

from ._models import ParsedQuery

# Filter token patterns: type:adr, feature:rag, date:2026-02,
# tag:#research, lang:python, path:src/,
# func:encode, class:Foo, nodetype:function_definition, intent:orientation,
# and the code-search noise-domain tokens exclude:tests / only:prod /
# include:docs (each value may be a comma-separated set).
_FILTER_PATTERN = re.compile(
    r"\b(type|feature|date|tag|lang|path|func|class|nodetype|intent|status"
    r"|exclude|only|include):(\S+)",
)

_FILTER_KEY_MAP = {
    "type": "doc_type",
    "feature": "feature",
    "date": "date",
    "lang": "language",
    "path": "path",
    "func": "function_name",
    "class": "class_name",
    "nodetype": "node_type",
    "intent": "intent",
    "status": "status",
    "exclude": "exclude_domain",
    "only": "only_domain",
    "include": "include_domain",
}

# Filter keys whose value is a comma-separated set; repeats accumulate.
_MULTI_VALUE_KEYS = frozenset({"exclude_domain", "only_domain", "include_domain"})


def parse_query(raw_query: str) -> ParsedQuery:
    """Parse a raw query string into text and metadata filters.

    Extracts structured filter tokens (e.g. ``type:adr``,
    ``feature:rag``) from the query and returns the remaining
    natural-language text alongside the parsed filters.

    Args:
        raw_query: Raw query string, possibly containing filter
            tokens such as ``type:adr`` or ``date:2026-02``.

    Returns:
        ParsedQuery with the cleaned text and extracted filters.
    """
    filters: dict[str, str] = {}

    for match in _FILTER_PATTERN.finditer(raw_query):
        key = match.group(1)
        value = match.group(2)

        if key == "tag":
            filters["tag"] = value.lstrip("#")
        elif key in _FILTER_KEY_MAP:
            mapped = _FILTER_KEY_MAP[key]
            if mapped in _MULTI_VALUE_KEYS and mapped in filters:
                # Repeated token (e.g. exclude:tests exclude:docs) accumulates.
                filters[mapped] = f"{filters[mapped]},{value}"
            else:
                filters[mapped] = value

    text = _FILTER_PATTERN.sub("", raw_query).strip()
    text = re.sub(r"\s+", " ", text)

    return ParsedQuery(text=text, filters=filters)
