"""Unit tests for dividing a markdown body into located passages."""

from __future__ import annotations

from typing import ClassVar

import pytest

from .._markdown_passages import PASSAGE_MAX_CHARS, Passage, parse_markdown

_BODY = """# Sample record title

## Considered options

- **Client watchdog (chosen).** Resolve the pipe creator and wait on it.
- **Idle timeout.** Rejected for now: kills long-lived quiet sessions.

## Implementation

Intro paragraph that is long enough to stand on its own as a passage, because it
explains in several words what the implementation does and why it does it.

### Migration

```python
# not a heading, this is inside a fence
value = 1
```

Closing words.
"""


def _text(structure_text: str, passage: Passage) -> str:
    return structure_text[passage.start : passage.end]


def _file_lines(text: str, first_line: int, passage: Passage) -> str:
    lines = text.split("\n")
    return "\n".join(
        lines[passage.line_start - first_line : passage.line_end - first_line + 1]
    )


class TestParseMarkdown:
    """Passage boundaries, sections and line spans."""

    pytestmark: ClassVar = [pytest.mark.unit]

    def test_sections_exclude_the_title_and_nest_below_it(self) -> None:
        structure = parse_markdown(_BODY)
        sections = [passage.section for passage in structure.passages]
        assert "Considered options" in sections
        assert "Implementation" in sections
        assert "Implementation > Migration" in sections
        assert all("Sample record title" not in section for section in sections)

    def test_a_hash_line_inside_a_fence_is_not_a_heading(self) -> None:
        structure = parse_markdown(_BODY)
        fenced = [p for p in structure.passages if "value = 1" in _text(_BODY, p)]
        assert len(fenced) == 1
        # With fence tracking removed, the fenced comment opens a section of its
        # own and this equality is the assertion that fails.
        assert fenced[0].section == "Implementation > Migration"
        assert "# not a heading" in _text(_BODY, fenced[0])
        closing = [p for p in structure.passages if "Closing" in _text(_BODY, p)]
        assert closing[0].section == "Implementation > Migration"

    def test_every_passage_is_verbatim_at_its_file_lines(self) -> None:
        first_line = 7
        structure = parse_markdown(_BODY, first_line=first_line)
        assert structure.passages
        for passage in structure.passages:
            text = _text(_BODY, passage)
            assert text == text.strip()
            assert _file_lines(_BODY, first_line, passage).strip() == text

    def test_a_list_below_the_merge_size_stays_whole(self) -> None:
        structure = parse_markdown(_BODY)
        options = [p for p in structure.passages if p.section == "Considered options"]
        assert len(options) == 1
        assert "Idle timeout" in _text(_BODY, options[0])

    def test_an_oversized_list_splits_at_items_within_the_bound(self) -> None:
        item = "- " + "word " * 60
        body = "## Options\n\n" + "\n".join(f"{item}{n}" for n in range(12))
        structure = parse_markdown(body)
        assert len(structure.passages) > 1
        for passage in structure.passages:
            text = _text(body, passage)
            assert len(text) <= PASSAGE_MAX_CHARS
            assert text.startswith("- ")

    def test_an_overlong_single_line_splits_at_sentences(self) -> None:
        body = " ".join(f"Sentence number {n} says something." for n in range(80))
        structure = parse_markdown(body)
        assert len(structure.passages) > 1
        for passage in structure.passages:
            text = _text(body, passage)
            assert len(text) <= PASSAGE_MAX_CHARS
            assert text.endswith(".")
            assert (passage.line_start, passage.line_end) == (1, 1)

    def test_a_short_lead_in_merges_into_the_next_passage(self) -> None:
        body = "## Notes\n\nShort lead-in:\n\n" + "A longer paragraph. " * 20
        structure = parse_markdown(body)
        assert len(structure.passages) == 1
        assert _text(body, structure.passages[0]).startswith("Short lead-in:")

    def test_short_passages_under_different_sections_stay_apart(self) -> None:
        body = "## One\n\nFirst.\n\n## Two\n\nSecond."
        structure = parse_markdown(body)
        assert [p.section for p in structure.passages] == ["One", "Two"]


class TestStructureQueries:
    """Clipping to a chunk, and section lookup at an offset."""

    pytestmark: ClassVar = [pytest.mark.unit]

    def test_clip_cuts_at_the_chunk_and_indexes_the_chunk_text(self) -> None:
        structure = parse_markdown(_BODY, first_line=10)
        cut = _BODY.index("kills long-lived")
        chunk_end = _BODY.index("## Implementation")
        clipped = structure.clip(cut, chunk_end)
        chunk_text = _BODY[cut:chunk_end]
        assert len(clipped) == 1
        piece = clipped[0]
        assert chunk_text[piece.start : piece.end].startswith("kills long-lived")
        assert piece.section == "Considered options"
        assert piece.line_start == structure.line_of(cut)

    def test_section_at_a_heading_line_is_the_path_above_it(self) -> None:
        structure = parse_markdown(_BODY)
        heading = _BODY.index("### Migration")
        assert structure.section_at(heading) == "Implementation"
        assert structure.section_at(heading + 1) == "Implementation > Migration"

    def test_span_lines_ignores_surrounding_blank_lines(self) -> None:
        structure = parse_markdown(_BODY, first_line=5)
        start = _BODY.index("## Implementation") - 1
        end = _BODY.index("### Migration")
        lines = structure.span_lines(start, end)
        assert lines is not None
        assert lines[0] == structure.line_of(start + 1)
        assert _BODY.split("\n")[lines[0] - 5] == "## Implementation"


class TestSetextAndBreaks:
    """Underlined headings open sections; thematic breaks are no passage."""

    pytestmark: ClassVar = [pytest.mark.unit]

    _SETEXT = (
        "Record title\n"
        "============\n"
        "\n"
        "Background\n"
        "----------\n"
        "\n"
        "Why the change was needed, in one short paragraph of prose.\n"
        "\n"
        "---\n"
        "\n"
        "Trailing note after a break.\n"
    )

    def test_an_underlined_line_is_a_heading_not_passage_text(self) -> None:
        structure = parse_markdown(self._SETEXT)
        texts = [_text(self._SETEXT, p) for p in structure.passages]
        # Treating the underline as ordinary text leaves this section empty and
        # the underline inside a passage, which is what these assertions reject.
        assert all(p.section == "Background" for p in structure.passages)
        assert not any("====" in text or "----" in text for text in texts)
        assert not any("Record title" in text for text in texts)

    def test_a_thematic_break_separates_blocks_without_becoming_one(self) -> None:
        structure = parse_markdown(self._SETEXT)
        texts = [_text(self._SETEXT, p) for p in structure.passages]
        assert "---" not in "\n".join(texts)
        assert any(text.startswith("Trailing note") for text in texts)

    def test_a_clip_inside_a_line_keeps_that_line_as_its_span(self) -> None:
        body = "## Notes\n\nalpha beta gamma delta epsilon zeta eta theta.\n"
        structure = parse_markdown(body, first_line=4)
        cut = body.index("delta")
        clipped = structure.clip(cut, len(body))
        assert len(clipped) == 1
        piece = clipped[0]
        chunk = body[cut:]
        line = body.split("\n")[piece.line_start - 4]
        assert chunk[piece.start : piece.end] in line
        assert piece.line_start == piece.line_end
