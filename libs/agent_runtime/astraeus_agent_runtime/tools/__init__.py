"""Agent tools — typed callables with allowlist enforcement.

Design principles:
1. Tools are typed Python callables: Pydantic input → Pydantic output.
2. Allowlists enforced at the dispatcher, not at the prompt.
3. All tools are read-only in Phase 6.
4. No tool exposes raw SQL or shell.
5. Tool outputs are size-capped with pagination.
"""

from astraeus_agent_runtime.tools.registry import (
    TOOL_REGISTRY,
    ToolDefinition,
    ToolNotAllowed,
    dispatch_tool,
    register_tool,
)

__all__ = [
    "TOOL_REGISTRY",
    "ToolDefinition",
    "ToolNotAllowed",
    "dispatch_tool",
    "register_tool",
]
