"""Answer-sized passages of a markdown body, with line spans and section paths.

A vault chunk is sized for embedding, not for reading: at a few thousand
characters it holds several paragraphs, and the one that answers a query is
rarely its opening. This module divides a markdown body into passages a reader
can take in whole - paragraphs, lists, tables and fenced blocks, never more
than :data:`PASSAGE_MAX_CHARS` - and records for each where it sits in the file
and which headings it falls under.

The division is made once over the whole body because only a whole-body pass
knows whether a line sits inside a fenced block and which headings are open
above it; a chunk read in isolation can know neither.

Dependency-free (stdlib only, no project imports, no ``torch``) so the vault
split workers can import it.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass
from functools import partial
from itertools import pairwise
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

__all__ = [
    "PASSAGE_MAX_CHARS",
    "SECTION_SEPARATOR",
    "MarkdownStructure",
    "Passage",
    "parse_markdown",
]

#: Upper bound on a passage's length. Large enough to hold a whole paragraph or
#: a short list with its lead-in, which is where an answering sentence sits;
#: small enough that a page of results stays readable inside an agent's budget.
PASSAGE_MAX_CHARS: Final = 1200

#: A passage shorter than this is folded into the next one under the same
#: heading, so a lone lead-in line is not offered as an answer on its own.
_MERGE_BELOW_CHARS: Final = 200

#: Joins heading texts into a section path, e.g. ``Implementation > Migration``.
SECTION_SEPARATOR: Final = " > "

_ATX_HEADING = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*$")
_SETEXT_UNDERLINE = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
_THEMATIC_BREAK = re.compile(r"^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")
_CLOSING_HASHES = re.compile(r"(?:^|[ \t]+)#+$")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
# Matched with ``pattern.match(text, pos)``, which anchors at *pos* by itself;
# a ``^`` here would only ever match at the start of the whole text.
_LIST_ITEM = re.compile(r" {0,3}(?:[-*+]|\d{1,9}[.)])(?:[ \t]|$)")
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])[ \t]+")
_SPACE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class Passage:
    """One passage: its offsets into the parsed text, file lines and section.

    ``start``/``end`` are character offsets (end exclusive) into whatever text
    the passage was taken from; ``line_start``/``line_end`` are 1-based file
    lines, both inclusive. ``section`` is the path of headings the passage
    sits under, without the document's title, or ``""`` above every heading.
    """

    start: int
    end: int
    line_start: int
    line_end: int
    section: str


@dataclass(frozen=True, slots=True)
class MarkdownStructure:
    """A parsed body: its passages and the section path set by every heading.

    ``line_offsets`` holds the offset each line of ``text`` starts at;
    ``heading_offsets`` and ``heading_sections`` pair each heading line's
    offset with the section path in force after it.
    """

    text: str
    first_line: int
    passages: tuple[Passage, ...]
    line_offsets: tuple[int, ...]
    heading_offsets: tuple[int, ...]
    heading_sections: tuple[str, ...]

    def line_of(self, offset: int) -> int:
        """Return the 1-based file line holding character *offset*."""
        return _line_of(self.line_offsets, self.first_line, offset)

    def section_at(self, offset: int) -> str:
        """Return the section path in force for text starting at *offset*."""
        index = bisect_right(self.heading_offsets, offset - 1)
        return self.heading_sections[index - 1] if index else ""

    def span_lines(self, start: int, end: int) -> tuple[int, int] | None:
        """Return the file lines of the non-blank text in ``[start, end)``."""
        trimmed = _trim(self.text, start, end)
        if trimmed is None:
            return None
        return self.line_of(trimmed[0]), self.line_of(trimmed[1] - 1)

    def clip(self, start: int, end: int) -> tuple[Passage, ...]:
        """Return the passages inside ``[start, end)``, cut at its edges.

        Offsets of the returned passages are relative to *start*, so they
        index the slice ``text[start:end]`` directly; lines stay file lines.
        """
        clipped: list[Passage] = []
        for passage in self.passages:
            if passage.end <= start or passage.start >= end:
                continue
            trimmed = _trim(self.text, max(passage.start, start), min(passage.end, end))
            if trimmed is None:
                continue
            low, high = trimmed
            clipped.append(
                Passage(
                    start=low - start,
                    end=high - start,
                    line_start=self.line_of(low),
                    line_end=self.line_of(high - 1),
                    section=passage.section,
                )
            )
        return tuple(clipped)


@dataclass(frozen=True, slots=True)
class _Scan:
    """The blocks and heading marks one pass over a body found."""

    blocks: list[tuple[int, int, str]]
    heading_offsets: list[int]
    heading_sections: list[str]


def parse_markdown(text: str, *, first_line: int = 1) -> MarkdownStructure:
    """Divide *text* into passages; *first_line* is the file line it starts on."""
    line_offsets: list[int] = []
    position = 0
    for line in text.split("\n"):
        line_offsets.append(position)
        position += len(line) + 1
    scan = _scan_blocks(text, line_offsets)
    spans = _merge_small(
        text,
        [
            (low, high, section)
            for start, end, section in scan.blocks
            for low, high in _bounded(text, start, end)
        ],
    )
    return MarkdownStructure(
        text=text,
        first_line=first_line,
        passages=tuple(
            Passage(
                start,
                end,
                _line_of(line_offsets, first_line, start),
                _line_of(line_offsets, first_line, end - 1),
                section,
            )
            for start, end, section in spans
        ),
        line_offsets=tuple(line_offsets),
        heading_offsets=tuple(scan.heading_offsets),
        heading_sections=tuple(scan.heading_sections),
    )


def _scan_blocks(text: str, line_offsets: Sequence[int]) -> _Scan:
    """Find the body's blocks: runs of non-blank lines, and whole fences.

    A heading closes the block before it and belongs to no block; its text
    instead joins the section path of every block below it. A thematic break
    separates blocks and belongs to none.
    """
    lines = text.split("\n")
    scan = _Scan(blocks=[], heading_offsets=[], heading_sections=[])
    stack: list[tuple[int, str]] = []
    block_first: int | None = None
    fence: str | None = None

    def close(last: int) -> None:
        nonlocal block_first
        if block_first is not None and last >= block_first:
            end = line_offsets[last] + len(lines[last])
            trimmed = _trim(text, line_offsets[block_first], end)
            if trimmed is not None:
                section = SECTION_SEPARATOR.join(title for _, title in stack)
                scan.blocks.append((trimmed[0], trimmed[1], section))
        block_first = None

    for index, line in enumerate(lines):
        if fence is not None:
            if _closes_fence(line, fence):
                close(index)
                fence = None
            continue
        opener = _FENCE.match(line)
        heading = None if opener else _heading_at(lines, index, block_first)
        if opener is not None:
            close(index - 1)
            block_first = index
            fence = opener.group(1)
        elif heading is not None:
            level, title, first = heading
            close(first - 1)
            _enter_heading(stack, level, title, is_first=not scan.heading_offsets)
            scan.heading_offsets.append(line_offsets[first])
            scan.heading_sections.append(
                SECTION_SEPARATOR.join(entry for _, entry in stack)
            )
        elif not line.strip() or _THEMATIC_BREAK.match(line):
            close(index - 1)
        elif block_first is None:
            block_first = index
    close(len(lines) - 1)
    return scan


def _heading_at(
    lines: list[str], index: int, block_first: int | None
) -> tuple[int, str, int] | None:
    """Return the heading ending on line *index*: its level, text and first line.

    An ATX heading is its own line. A setext heading is a single line of text
    underlined by ``=`` (level 1) or ``-`` (level 2), so it is recognised on
    the underline, with the open block of exactly that one line as its text.
    """
    atx = _ATX_HEADING.match(lines[index])
    if atx is not None:
        title = _CLOSING_HASHES.sub("", atx.group(2) or "").strip()
        return len(atx.group(1)), title, index
    underline = _SETEXT_UNDERLINE.match(lines[index])
    if underline is not None and block_first is not None and block_first == index - 1:
        level = 1 if underline.group(1).startswith("=") else 2
        return level, lines[index - 1].strip(), index - 1
    return None


def _enter_heading(
    stack: list[tuple[int, str]], level: int, title: str, *, is_first: bool
) -> None:
    # The first heading, when it is an H1, is the document's title; results
    # carry the title on their own, so section paths start below it.
    if is_first and level == 1:
        return
    stack[:] = [entry for entry in stack if entry[0] < level]
    stack.append((level, title))


def _line_of(line_offsets: Sequence[int], first_line: int, offset: int) -> int:
    return first_line + bisect_right(line_offsets, offset) - 1


def _closes_fence(line: str, opener: str) -> bool:
    stripped = line.strip()
    return (
        len(stripped) >= len(opener)
        and set(stripped) == {opener[0]}
        and len(line) - len(line.lstrip(" ")) <= 3
    )


def _trim(text: str, start: int, end: int) -> tuple[int, int] | None:
    """Narrow ``[start, end)`` to its non-whitespace extent, or ``None``."""
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return (start, end) if start < end else None


def _bounded(text: str, start: int, end: int) -> list[tuple[int, int]]:
    """Cut one block into pieces of at most :data:`PASSAGE_MAX_CHARS`.

    Finer boundaries are tried only where a coarser piece is still too long:
    list items first, then lines, then sentences, then words, and a hard cut
    only for a single word longer than the bound.
    """
    if end - start <= PASSAGE_MAX_CHARS:
        return [(start, end)]
    splitters: tuple[Callable[[str, int, int], list[tuple[int, int]]], ...] = (
        _list_items,
        _lines,
        partial(_after_breaks, _SENTENCE_BREAK),
        partial(_after_breaks, _SPACE),
    )
    for splitter in splitters:
        parts = splitter(text, start, end)
        if len(parts) > 1:
            return _pack(
                [atom for low, high in parts for atom in _bounded(text, low, high)]
            )
    return [
        (low, min(low + PASSAGE_MAX_CHARS, end))
        for low in range(start, end, PASSAGE_MAX_CHARS)
    ]


def _pack(atoms: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Greedily join consecutive atoms while the joined span fits the bound."""
    packed: list[tuple[int, int]] = []
    for low, high in atoms:
        if packed and high - packed[-1][0] <= PASSAGE_MAX_CHARS:
            packed[-1] = (packed[-1][0], high)
        else:
            packed.append((low, high))
    return packed


def _pieces(text: str, start: int, cuts: list[int], end: int) -> list[tuple[int, int]]:
    pieces = (_trim(text, low, high) for low, high in pairwise([start, *cuts, end]))
    return [piece for piece in pieces if piece is not None]


def _line_starts(text: str, start: int, end: int) -> list[int]:
    starts: list[int] = []
    position = text.find("\n", start, end)
    while position != -1:
        starts.append(position + 1)
        position = text.find("\n", position + 1, end)
    return starts


def _list_items(text: str, start: int, end: int) -> list[tuple[int, int]]:
    cuts = [
        position
        for position in _line_starts(text, start, end)
        if _LIST_ITEM.match(text, position, end) is not None
    ]
    return _pieces(text, start, cuts, end)


def _lines(text: str, start: int, end: int) -> list[tuple[int, int]]:
    return _pieces(text, start, _line_starts(text, start, end), end)


def _after_breaks(
    pattern: re.Pattern[str], text: str, start: int, end: int
) -> list[tuple[int, int]]:
    """Cut ``[start, end)`` after every match of *pattern*."""
    cuts = [match.end() for match in pattern.finditer(text, start, end)]
    return _pieces(text, start, cuts, end)


def _merge_small(
    text: str, spans: list[tuple[int, int, str]]
) -> list[tuple[int, int, str]]:
    """Fold each short passage into the next one it sits beside.

    Only whitespace may lie between the two: a merged passage is shown
    verbatim, so anything the scan set aside between them - a thematic break,
    a heading - would otherwise reappear inside it.
    """
    merged: list[tuple[int, int, str]] = []
    for start, end, section in spans:
        if merged:
            previous_start, previous_end, previous_section = merged[-1]
            if (
                previous_section == section
                and previous_end - previous_start < _MERGE_BELOW_CHARS
                and end - previous_start <= PASSAGE_MAX_CHARS
                and not text[previous_end:start].strip()
            ):
                merged[-1] = (previous_start, end, section)
                continue
        merged.append((start, end, section))
    return merged
