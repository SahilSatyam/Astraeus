"""Unit tests for the prompt registry."""

from __future__ import annotations

from astraeus_agent_runtime.prompt_registry import (
    PromptEntry,
    PromptRegistry,
    create_default_registry,
)


class TestPromptRegistry:
    """Test prompt registry operations."""

    def test_register_and_get(self) -> None:
        registry = PromptRegistry()
        entry = PromptEntry(
            prompt_key="test.system",
            version="v1.0",
            body="You are a test agent.",
            status="promoted",
        )
        registry.register(entry)
        result = registry.get("test.system")
        assert result is not None
        assert result.body == "You are a test agent."

    def test_get_by_version(self) -> None:
        registry = PromptRegistry()
        registry.register(
            PromptEntry(prompt_key="agent.sys", version="v1.0", body="v1 body", status="promoted")
        )
        registry.register(
            PromptEntry(prompt_key="agent.sys", version="v2.0", body="v2 body", status="candidate")
        )

        v1 = registry.get("agent.sys", version="v1.0")
        assert v1 is not None
        assert v1.body == "v1 body"

        v2 = registry.get("agent.sys", version="v2.0")
        assert v2 is not None
        assert v2.body == "v2 body"

    def test_get_by_channel(self) -> None:
        registry = PromptRegistry()
        registry.register(
            PromptEntry(prompt_key="agent.sys", version="v1.0", body="promoted", status="promoted")
        )
        registry.register(
            PromptEntry(
                prompt_key="agent.sys", version="v2.0", body="candidate", status="candidate"
            )
        )

        promoted = registry.get("agent.sys", channel="promoted")
        assert promoted is not None
        assert promoted.body == "promoted"

        candidate = registry.get("agent.sys", channel="candidate")
        assert candidate is not None
        assert candidate.body == "candidate"

    def test_get_nonexistent_returns_none(self) -> None:
        registry = PromptRegistry()
        assert registry.get("nonexistent") is None

    def test_promote(self) -> None:
        registry = PromptRegistry()
        registry.register(
            PromptEntry(prompt_key="a.sys", version="v1.0", body="old", status="promoted")
        )
        registry.register(
            PromptEntry(prompt_key="a.sys", version="v2.0", body="new", status="candidate")
        )

        success = registry.promote("a.sys", "v2.0")
        assert success is True

        # v2 is now promoted
        current = registry.get("a.sys", channel="promoted")
        assert current is not None
        assert current.version == "v2.0"

        # v1 is retired
        v1 = registry.get("a.sys", version="v1.0")
        assert v1 is not None
        assert v1.status == "retired"

    def test_promote_nonexistent_fails(self) -> None:
        registry = PromptRegistry()
        assert registry.promote("nope", "v1.0") is False

    def test_content_hash(self) -> None:
        entry = PromptEntry(prompt_key="x", version="v1", body="hello world")
        assert len(entry.content_hash) == 16
        # Same body = same hash
        entry2 = PromptEntry(prompt_key="y", version="v2", body="hello world")
        assert entry.content_hash == entry2.content_hash

    def test_list_entries(self) -> None:
        registry = PromptRegistry()
        registry.register(PromptEntry(prompt_key="a", version="v1", body="a1"))
        registry.register(PromptEntry(prompt_key="b", version="v1", body="b1"))
        assert len(registry.list_entries()) == 2
        assert len(registry.list_entries(key="a")) == 1


class TestDefaultRegistry:
    """Test the default prompt registry creation."""

    def test_default_registry_has_agents(self) -> None:
        registry = create_default_registry()
        assert registry.get("research_agent.system") is not None
        assert registry.get("sentiment_agent.system") is not None
        assert registry.get("risk_agent.system") is not None
        assert registry.get("compliance_agent.system") is not None

    def test_default_prompts_are_promoted(self) -> None:
        registry = create_default_registry()
        entry = registry.get("research_agent.system")
        assert entry is not None
        assert entry.status == "promoted"
        assert entry.promoted_at is not None
