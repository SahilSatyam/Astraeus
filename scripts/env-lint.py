"""Verify ``.env.example`` is a superset of every variable referenced in Settings.

Reads ``.env.example`` (KEY=VALUE lines) and walks every ``BaseSettings`` model
in :mod:`astraeus_config`, projecting their fields into ``ASTRAEUS_<PREFIX><FIELD>``
form. Any variable referenced by Settings but missing from ``.env.example`` is
a CI-failable lint.

Run::

    uv run python scripts/env-lint.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from astraeus_config import (
    AppSettings,
    DatabaseSettings,
    ObservabilitySettings,
    RedisSettings,
    Settings,
)
from pydantic_settings import BaseSettings


def _expected_vars() -> set[str]:
    expected: set[str] = set()
    sub_models: list[type[BaseSettings]] = [
        AppSettings,
        DatabaseSettings,
        RedisSettings,
        ObservabilitySettings,
    ]
    for model in sub_models:
        prefix = _env_prefix(model)
        for name in model.model_fields:
            expected.add(f"{prefix}{name}".upper())

    # Top-level Settings has its own non-prefixed fields (e.g. ``env``).
    for name, info in Settings.model_fields.items():
        if _is_submodel(info.annotation):
            continue
        expected.add(f"ASTRAEUS_{name}".upper())

    return expected


def _env_prefix(model: type[BaseSettings]) -> str:
    config = model.model_config
    return str(config.get("env_prefix", "ASTRAEUS_"))


def _is_submodel(annotation: Any) -> bool:
    if annotation is None:
        return False
    try:
        return issubclass(annotation, BaseSettings)
    except TypeError:
        return False


def _present_vars(env_path: Path) -> set[str]:
    seen: set[str] = set()
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, _, _ = line.partition("=")
        if key:
            seen.add(key.upper())
    return seen


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    env_example = repo_root / ".env.example"
    if not env_example.exists():
        print(f"ERROR: {env_example} does not exist.", file=sys.stderr)
        return 2

    expected = _expected_vars()
    present = _present_vars(env_example)

    missing = sorted(expected - present)
    extra = sorted(present - expected)

    if missing:
        print("Missing from .env.example:", file=sys.stderr)
        for name in missing:
            print(f"  - {name}", file=sys.stderr)
    if extra:
        # Extras are warnings, not errors — projects often document docker-only
        # env vars (e.g. POSTGRES_PASSWORD) that aren't read by Settings.
        print("Note: present in .env.example but not in Settings (advisory):")
        for name in extra:
            print(f"  - {name}")

    if missing:
        return 1

    print(f"OK: .env.example covers all {len(expected)} Settings variables.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
