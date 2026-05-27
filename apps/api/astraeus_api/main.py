"""Uvicorn entrypoint.

Usage::

    uv run uvicorn astraeus_api.main:app --host 0.0.0.0 --port 8000

The module-level ``app`` is built lazily from environment-driven settings, so
that test harnesses that override settings via :func:`astraeus_api.create_app`
never trigger the global ``app`` import path.
"""

from __future__ import annotations

from astraeus_api.app import create_app

app = create_app()
