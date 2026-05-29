"""Text cleaner — normalizes raw document text for NLP processing.

Handles:
- HTML stripping (SEC filings, RSS content)
- Unicode normalization
- Whitespace collapse
- Boilerplate removal (headers, footers, legal disclaimers)
- URL removal (optional)
- Emoji/special char handling
"""

from __future__ import annotations

import re
import unicodedata

import structlog

logger = structlog.get_logger("astraeus.nlp.cleaner")

# Patterns to strip
_URL_RE = re.compile(r"https?://\S+")
_EMAIL_RE = re.compile(r"\S+@\S+\.\S+")
_MULTIPLE_NEWLINES = re.compile(r"\n{3,}")
_MULTIPLE_SPACES = re.compile(r"[ \t]{2,}")
_BOILERPLATE_PATTERNS = [
    re.compile(r"(?i)forward[- ]looking statements?.*?(?:\n\n|\Z)", re.DOTALL),
    re.compile(r"(?i)safe harbor.*?(?:\n\n|\Z)", re.DOTALL),
    re.compile(r"(?i)this (press release|document) contains.*?(?:\n\n|\Z)", re.DOTALL),
]


def clean_html(html: str) -> str:
    """Strip HTML tags and extract text content.

    Uses BeautifulSoup for robust HTML parsing. Falls back to regex
    stripping if BS4 fails.
    """
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "lxml")

        # Remove script and style elements
        for element in soup(["script", "style", "head", "nav", "footer"]):
            element.decompose()

        text = soup.get_text(separator="\n")
    except Exception:
        # Fallback: regex strip
        text = re.sub(r"<[^>]+>", " ", html)

    return text


def normalize_unicode(text: str) -> str:
    """Normalize Unicode to NFC form and replace special chars."""
    text = unicodedata.normalize("NFC", text)
    # Replace common Unicode quotes/dashes with ASCII equivalents
    replacements = {
        "\u2018": "'",
        "\u2019": "'",  # smart quotes
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",  # en/em dash
        "\u2026": "...",  # ellipsis
        "\xa0": " ",  # non-breaking space
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def remove_urls(text: str) -> str:
    """Remove URLs from text."""
    return _URL_RE.sub("", text)


def remove_emails(text: str) -> str:
    """Remove email addresses from text."""
    return _EMAIL_RE.sub("[EMAIL]", text)


def collapse_whitespace(text: str) -> str:
    """Collapse multiple spaces/newlines into single ones."""
    text = _MULTIPLE_SPACES.sub(" ", text)
    text = _MULTIPLE_NEWLINES.sub("\n\n", text)
    return text.strip()


def remove_boilerplate(text: str) -> str:
    """Remove common financial document boilerplate.

    Targets forward-looking statement disclaimers and safe harbor notices.
    These add noise to sentiment analysis without informational content.
    """
    for pattern in _BOILERPLATE_PATTERNS:
        text = pattern.sub("", text)
    return text


def clean_document(
    text: str,
    *,
    strip_html: bool = True,
    strip_urls: bool = True,
    strip_emails: bool = True,
    strip_boilerplate: bool = True,
) -> str:
    """Full cleaning pipeline for a document.

    Args:
        text: Raw document text (may contain HTML).
        strip_html: Whether to strip HTML tags.
        strip_urls: Whether to remove URLs.
        strip_emails: Whether to redact email addresses.
        strip_boilerplate: Whether to remove financial boilerplate.

    Returns:
        Cleaned text ready for chunking and NLP processing.
    """
    if not text:
        return ""

    if strip_html and ("<" in text and ">" in text):
        text = clean_html(text)

    text = normalize_unicode(text)

    if strip_urls:
        text = remove_urls(text)

    if strip_emails:
        text = remove_emails(text)

    if strip_boilerplate:
        text = remove_boilerplate(text)

    text = collapse_whitespace(text)

    return text
