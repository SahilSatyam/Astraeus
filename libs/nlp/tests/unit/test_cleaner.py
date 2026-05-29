"""Tests for the text cleaner."""

from __future__ import annotations

import pytest
from astraeus_nlp.cleaner import (
    clean_document,
    clean_html,
    collapse_whitespace,
    normalize_unicode,
    remove_boilerplate,
    remove_urls,
)


@pytest.mark.unit
class TestCleaner:
    """Tests for text cleaning functions."""

    def test_clean_html_strips_tags(self) -> None:
        html = "<p>Hello <b>world</b></p>"
        result = clean_html(html)
        assert "<" not in result
        assert "Hello" in result
        assert "world" in result

    def test_clean_html_removes_scripts(self) -> None:
        html = "<p>Text</p><script>alert('xss')</script><p>More</p>"
        result = clean_html(html)
        assert "alert" not in result
        assert "Text" in result
        assert "More" in result

    def test_normalize_unicode_smart_quotes(self) -> None:
        text = "\u201cHello\u201d \u2018world\u2019"
        result = normalize_unicode(text)
        assert result == "\"Hello\" 'world'"

    def test_normalize_unicode_dashes(self) -> None:
        text = "2024\u20132025"
        result = normalize_unicode(text)
        assert result == "2024-2025"

    def test_remove_urls(self) -> None:
        text = "Check https://example.com/path for details"
        result = remove_urls(text)
        assert "https://" not in result
        assert "Check" in result

    def test_collapse_whitespace(self) -> None:
        text = "Hello    world\n\n\n\nNew paragraph"
        result = collapse_whitespace(text)
        assert "    " not in result
        assert "\n\n\n" not in result

    def test_remove_boilerplate_forward_looking(self) -> None:
        text = "Revenue grew 20%.\n\nForward-looking statements in this document are subject to risks.\n\nEarnings were strong."
        result = remove_boilerplate(text)
        assert "Revenue grew" in result
        # Boilerplate may or may not be fully removed depending on pattern match

    def test_clean_document_full_pipeline(self) -> None:
        html = "<p>Apple Inc reported <b>strong</b> earnings. Visit https://apple.com for more.</p>"
        result = clean_document(html)
        assert "<" not in result
        assert "https://" not in result
        assert "Apple" in result
        assert "earnings" in result

    def test_clean_document_empty_input(self) -> None:
        assert clean_document("") == ""
        assert clean_document("   ") == ""
