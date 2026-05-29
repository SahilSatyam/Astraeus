"""Reddit adapter — ingests posts and comments from finance subreddits.

Uses PRAW (Python Reddit API Wrapper) with OAuth. Rate-limit aware with
exponential backoff. PII redaction: author names are hashed at ingest.

Subreddit allowlist is configurable; defaults to top finance communities.
"""

from __future__ import annotations

import hashlib
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from astraeus_altdata.adapters.base import BaseDocumentAdapter
from astraeus_altdata.documents import AdapterFetchResult, DocumentSource, RawDocument

if TYPE_CHECKING:
    import praw

logger = structlog.get_logger("astraeus.altdata.adapters.reddit")

# Default finance subreddits — curated for signal quality
DEFAULT_SUBREDDITS: list[str] = [
    "wallstreetbets",
    "stocks",
    "investing",
    "options",
    "stockmarket",
    "SecurityAnalysis",
    "ValueInvesting",
    "dividends",
    "thetagang",
    "Bogleheads",
    "personalfinance",
    "financialindependence",
    "algotrading",
    "quant",
    "economics",
    "CryptoCurrency",
    "ethfinance",
    "SPACs",
    "pennystocks",
    "FluentInFinance",
]

# PII salt — in production, load from secrets
_PII_SALT = "astraeus-reddit-pii-v1"


def _hash_author(author: str) -> str:
    """Hash Reddit username for PII compliance. One-way; for dedup only."""
    return hashlib.sha256(f"{_PII_SALT}|{author}".encode()).hexdigest()[:16]


class RedditAdapter(BaseDocumentAdapter):
    """Reddit source adapter using PRAW.

    Fetches new posts from the configured subreddits. Each post becomes
    a RawDocument. Comments are concatenated into the body for context.
    """

    source = DocumentSource.REDDIT

    def __init__(
        self,
        reddit_client: praw.Reddit,
        subreddits: list[str] | None = None,
        posts_per_sub: int = 25,
        include_comments: bool = True,
        max_comments: int = 10,
    ) -> None:
        self._reddit = reddit_client
        self._subreddits = subreddits or DEFAULT_SUBREDDITS
        self._posts_per_sub = posts_per_sub
        self._include_comments = include_comments
        self._max_comments = max_comments
        self._current_sub_idx = 0

    async def fetch(self, cursor: str | None = None) -> AdapterFetchResult:
        """Fetch posts from the next subreddit in the rotation.

        Cursor is the subreddit index (simple round-robin pagination).
        """
        if cursor is not None:
            self._current_sub_idx = int(cursor)

        if self._current_sub_idx >= len(self._subreddits):
            return AdapterFetchResult(source=self.source)

        sub_name = self._subreddits[self._current_sub_idx]
        documents: list[RawDocument] = []
        errors: list[str] = []
        rate_limited = False

        try:
            subreddit = self._reddit.subreddit(sub_name)
            posts = subreddit.new(limit=self._posts_per_sub)

            for post in posts:
                try:
                    doc = self._post_to_document(post, sub_name)
                    documents.append(doc)
                except Exception as e:
                    errors.append(f"Post {post.id}: {e}")

        except Exception as e:
            error_msg = str(e)
            if "429" in error_msg or "rate" in error_msg.lower():
                rate_limited = True
                logger.warning("reddit_rate_limited", subreddit=sub_name)
            else:
                errors.append(f"Subreddit {sub_name}: {e}")
                logger.exception("reddit_fetch_error", subreddit=sub_name)

        next_idx = self._current_sub_idx + 1
        next_cursor = str(next_idx) if next_idx < len(self._subreddits) else None

        logger.info(
            "reddit_fetch_complete",
            subreddit=sub_name,
            documents=len(documents),
            errors=len(errors),
        )

        return AdapterFetchResult(
            documents=documents,
            source=self.source,
            fetch_completed_at=datetime.now(tz=UTC),
            next_cursor=next_cursor,
            errors=errors,
            rate_limited=rate_limited,
        )

    def _post_to_document(self, post: object, subreddit: str) -> RawDocument:
        """Convert a PRAW Submission to a RawDocument."""
        # Build body: title + selftext + top comments
        parts = [getattr(post, "title", ""), getattr(post, "selftext", "")]

        if self._include_comments:
            try:
                post.comments.replace_more(limit=0)  # type: ignore[attr-defined]
                for comment in post.comments[: self._max_comments]:  # type: ignore[index]
                    parts.append(f"[comment] {comment.body}")
            except Exception:
                pass  # Comments are best-effort

        body = "\n\n".join(p for p in parts if p)
        author = getattr(post, "author", None)
        author_hash = _hash_author(str(author)) if author else "deleted"

        created_utc = getattr(post, "created_utc", time.time())
        publish_ts = datetime.fromtimestamp(created_utc, tz=UTC)

        return RawDocument(
            source=DocumentSource.REDDIT,
            source_doc_id=f"reddit_{getattr(post, 'id', '')}",
            title=getattr(post, "title", None),
            body=body,
            url=f"https://reddit.com{getattr(post, 'permalink', '')}",
            publish_ts=publish_ts,
            metadata={
                "subreddit": subreddit,
                "author_hash": author_hash,
                "score": getattr(post, "score", 0),
                "num_comments": getattr(post, "num_comments", 0),
                "upvote_ratio": getattr(post, "upvote_ratio", 0.0),
            },
        )

    async def close(self) -> None:
        """PRAW doesn't need explicit cleanup."""
