"""Dependency-free HTML-to-text normalisation for the chunk worker.

Strips tags from ``.html`` sources before chunking so raw markup does not waste
a third of every chunk's budget on non-semantic tokens (#185 adjacent ask).
Uses the stdlib :class:`html.parser.HTMLParser` only - no new dependency and
torch-free, so it is safe to import in the CPU-only spawn worker. Script and
style bodies are dropped; block-level close tags emit a newline so the
``TextSplitter`` still finds paragraph/line structure.
"""

from __future__ import annotations

import logging
from html.parser import HTMLParser

logger = logging.getLogger(__name__)

__all__ = ["html_to_text"]

# Tags whose text content is non-semantic and should be dropped entirely.
_SKIP_CONTENT_TAGS = frozenset({"script", "style", "head", "noscript", "template"})

# Block-level tags that should produce a line break when they close, so the
# splitter's "\n\n"/"\n" separators still find structure after stripping.
_BLOCK_TAGS = frozenset(
    {
        "p",
        "div",
        "section",
        "article",
        "header",
        "footer",
        "main",
        "aside",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "li",
        "ul",
        "ol",
        "tr",
        "table",
        "thead",
        "tbody",
        "br",
        "hr",
        "pre",
        "blockquote",
        "figure",
        "figcaption",
        "nav",
    }
)


class _TextExtractor(HTMLParser):
    """Collects visible text, suppressing script/style bodies."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs  # tag attributes are irrelevant to text extraction
        if tag in _SKIP_CONTENT_TAGS:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_CONTENT_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._parts.append(data)

    def get_text(self) -> str:
        return "".join(self._parts)


def html_to_text(html: str) -> str:
    """Return the visible text of an HTML document, tags stripped.

    Collapses runs of blank lines and trims trailing whitespace per line so the
    output is splitter-friendly. On any parse error the original markup is
    returned unchanged, so HTML indexing never regresses (#185).

    Args:
        html: Raw HTML source.

    Returns:
        Plain text, or the original ``html`` if parsing fails.
    """
    try:
        parser = _TextExtractor()
        parser.feed(html)
        parser.close()
        text = parser.get_text()
    except (ValueError, AssertionError) as exc:
        logger.debug("HTML strip failed; keeping raw markup: %s", exc)
        return html

    lines = [line.strip() for line in text.splitlines()]
    collapsed: list[str] = []
    blank = False
    for line in lines:
        if line:
            collapsed.append(line)
            blank = False
        elif not blank:
            collapsed.append("")
            blank = True
    return "\n".join(collapsed).strip()
