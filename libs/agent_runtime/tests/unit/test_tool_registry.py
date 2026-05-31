"""Unit tests for the tool registry and dispatcher."""

from __future__ import annotations

import pytest
from astraeus_agent_runtime.tools.registry import (
    AGENT_TOOL_ALLOWLISTS,
    TOOL_REGISTRY,
    ToolDefinition,
    ToolNotAllowed,
    dispatch_tool,
    register_tool,
)


class TestToolRegistry:
    """Test tool registration."""

    def test_register_tool(self) -> None:
        tool = ToolDefinition(
            name="test_tool_reg",
            description="A test tool",
            version="1.0.0",
        )
        register_tool(tool)
        assert "test_tool_reg" in TOOL_REGISTRY
        assert TOOL_REGISTRY["test_tool_reg"].version == "1.0.0"

    def test_tool_definition_fields(self) -> None:
        tool = ToolDefinition(
            name="my_tool",
            description="Does something",
            version="2.1.0",
            read_only=True,
        )
        assert tool.name == "my_tool"
        assert tool.description == "Does something"
        assert tool.version == "2.1.0"
        assert tool.read_only is True


class TestAllowlistEnforcement:
    """Test that tool allowlists are enforced."""

    def test_research_agent_allowed_tools(self) -> None:
        allowed = AGENT_TOOL_ALLOWLISTS["research"]
        assert "search_news" in allowed
        assert "fetch_filing" in allowed
        assert "run_risk_check" not in allowed

    def test_risk_agent_allowed_tools(self) -> None:
        allowed = AGENT_TOOL_ALLOWLISTS["risk"]
        assert "run_risk_check" in allowed
        assert "get_portfolio_state" in allowed
        assert "search_news" not in allowed

    def test_execution_agent_has_no_order_tools(self) -> None:
        """Critical: execution agent must NEVER have order tools."""
        allowed = AGENT_TOOL_ALLOWLISTS["execution"]
        assert "place_order" not in allowed
        assert "cancel_order" not in allowed
        assert "modify_order" not in allowed

    def test_compliance_agent_tools(self) -> None:
        allowed = AGENT_TOOL_ALLOWLISTS["compliance"]
        assert "lookup_restricted_list" in allowed
        assert "write_audit_envelope" in allowed


class TestToolDispatch:
    """Test the tool dispatcher."""

    @pytest.mark.asyncio
    async def test_dispatch_not_allowed_raises(self) -> None:
        """Dispatching a tool not in the agent's allowlist raises ToolNotAllowed."""
        with pytest.raises(ToolNotAllowed) as exc_info:
            await dispatch_tool(
                agent_name="research",
                tool_name="run_risk_check",
                payload={},
            )
        assert "research" in str(exc_info.value)
        assert "run_risk_check" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_dispatch_unregistered_tool_raises(self) -> None:
        """Dispatching a tool that doesn't exist raises KeyError."""
        # Add a fake tool to the allowlist temporarily
        AGENT_TOOL_ALLOWLISTS.setdefault("test_agent", set()).add("nonexistent_tool")
        try:
            with pytest.raises(KeyError):
                await dispatch_tool(
                    agent_name="test_agent",
                    tool_name="nonexistent_tool",
                    payload={},
                )
        finally:
            del AGENT_TOOL_ALLOWLISTS["test_agent"]
