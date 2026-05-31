"""Import-graph audit: enforce LLM/agent → broker isolation.

Architectural rule: there is NO code path from any agent module to any
broker SDK. This script verifies that rule at CI time.

Forbidden import paths:
- libs/agents/** cannot import from libs/brokers/**
- libs/agents/** cannot import from apps/oms/**
- libs/recommender/**/stages/thesis.py cannot import from libs/brokers/**
- apps/oms/** cannot import from libs/agent_runtime/**

Run: python scripts/import_audit.py
Exit code 0 = pass, 1 = violation found.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

# Define forbidden import rules
# (source_glob, forbidden_module_prefixes, description)
RULES: list[tuple[str, list[str], str]] = [
    (
        "libs/agent_runtime/**/*.py",
        ["astraeus_brokers", "astraeus_oms", "alpaca", "ib_insync", "binance"],
        "Agent runtime must not import broker/OMS modules",
    ),
    (
        "libs/recommender/**/*.py",
        ["astraeus_brokers", "astraeus_oms", "alpaca", "ib_insync", "binance"],
        "Recommender must not import broker/OMS modules",
    ),
    (
        "apps/oms/**/*.py",
        ["astraeus_agent_runtime", "astraeus_recommender"],
        "OMS must not import agent/recommender modules",
    ),
    (
        "libs/brokers/**/*.py",
        ["astraeus_agent_runtime", "astraeus_recommender"],
        "Brokers must not import agent/recommender modules",
    ),
]


def get_imports(filepath: Path) -> list[str]:
    """Extract all import module names from a Python file."""
    try:
        tree = ast.parse(filepath.read_text(encoding="utf-8"))
    except SyntaxError:
        return []

    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)
    return imports


def check_rule(
    root: Path, source_glob: str, forbidden_prefixes: list[str], description: str
) -> list[str]:
    """Check a single rule. Returns list of violation messages."""
    violations: list[str] = []
    for filepath in root.glob(source_glob):
        if not filepath.is_file():
            continue
        # Skip __pycache__
        if "__pycache__" in str(filepath):
            continue

        imports = get_imports(filepath)
        for imp in imports:
            for prefix in forbidden_prefixes:
                if imp == prefix or imp.startswith(f"{prefix}."):
                    rel = filepath.relative_to(root)
                    violations.append(
                        f"  VIOLATION: {rel} imports '{imp}' ({description})"
                    )
    return violations


def main() -> int:
    root = Path(__file__).parent.parent
    all_violations: list[str] = []

    print("=" * 60)
    print("Import-Graph Audit: LLM/Agent ↔ Broker Isolation")
    print("=" * 60)

    for source_glob, forbidden, description in RULES:
        violations = check_rule(root, source_glob, forbidden, description)
        if violations:
            all_violations.extend(violations)
            print(f"\nFAIL: {description}")
            for v in violations:
                print(v)
        else:
            print(f"  OK: {description}")

    print()
    if all_violations:
        print(f"FAILED: {len(all_violations)} violation(s) found.")
        return 1
    else:
        print("PASSED: No import isolation violations.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
