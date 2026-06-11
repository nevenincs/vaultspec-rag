"""Unit tests for HTML-to-text normalisation and the new text extensions (no GPU).

Exercises the #185 adjacent asks: stdlib ``html_to_text`` drops tags/script/style
and decodes entities, the worker honours the ``html_strip`` toggle for ``.html``
sources, and the new plain-text extensions chunk as text.
"""

from pathlib import Path

import pytest

from ..indexer._chunk_worker import _chunk_decoded
from ..indexer._html import html_to_text

pytestmark = [pytest.mark.unit]


def test_strips_tags_keeps_text() -> None:
    out = html_to_text("<html><body><p>Hello <b>world</b></p></body></html>")
    assert "Hello" in out
    assert "world" in out
    assert "<" not in out and ">" not in out


def test_drops_script_and_style_bodies() -> None:
    html = (
        "<html><head><style>.x{color:red}</style></head>"
        "<body><script>var secret = 1;</script>"
        "<p>visible text</p></body></html>"
    )
    out = html_to_text(html)
    assert "visible text" in out
    assert "secret" not in out
    assert "color:red" not in out


def test_decodes_entities() -> None:
    out = html_to_text("<p>a &amp; b &lt; c</p>")
    assert "a & b < c" in out


def test_block_tags_produce_line_structure() -> None:
    out = html_to_text("<p>first para</p><p>second para</p>")
    assert "first para" in out
    assert "second para" in out
    assert "\n" in out  # blocks separated so the splitter finds structure


def test_malformed_html_does_not_raise() -> None:
    # Unclosed tags / stray brackets must never raise - worst case returns text.
    out = html_to_text("<p>unclosed <b>bold <<< and more")
    assert "unclosed" in out


def test_chunk_decoded_strips_html_when_enabled(tmp_path: Path) -> None:
    path = tmp_path / "page.html"
    html = "<html><body><nav>menu menu menu</nav><p>real content here</p></body></html>"
    chunks = _chunk_decoded(html, path, tmp_path, html_strip=True)
    joined = " ".join(c.content for c in chunks)
    assert "real content here" in joined
    assert "<p>" not in joined


def test_chunk_decoded_keeps_markup_when_disabled(tmp_path: Path) -> None:
    path = tmp_path / "page.html"
    html = "<html><body><p>real content here</p></body></html>"
    chunks = _chunk_decoded(html, path, tmp_path, html_strip=False)
    joined = " ".join(c.content for c in chunks)
    assert "<p>" in joined


def test_new_text_extensions_chunk_as_text(tmp_path: Path) -> None:
    for name, body in (
        ("notes.txt", "plain text line one\nline two"),
        ("config.properties", "key=value\nother=thing"),
        ("schema.xsd", "<xs:schema><xs:element name='a'/></xs:schema>"),
    ):
        path = tmp_path / name
        chunks = _chunk_decoded(body, path, tmp_path, html_strip=True)
        assert chunks, name
        assert any(c.content.strip() for c in chunks), name
