"""Base agent class — defines the contract all agents implement."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import structlog
from pydantic import BaseModel

from astraeus_agent_runtime.llm_client import LLMClient
from astraeus_agent_runtime.prompt_registry import PromptRegistry

logger = structlog.get_logger("astraeus.agent_runtime.agents")


@dataclass(frozen=True, slots=True)
class AgentSpec:
    """Specification for an agent — its identity and constraints."""

    name: str
    prompt_key: str  # Key in prompt registry
    output_schema: type[BaseModel]
    allowed_tools: frozenset[str] = frozenset()
    model_tier: str = "reasoning"  # reasoning | synthesis | classification | cheap
    max_retries: int = 2  # Schema repair loop bound


class BaseAgent(ABC):
    """Base class for all agents in the runtime.

    Subclasses implement `execute()` which receives the relevant
    slice of run state and returns a structured output.
    """

    def __init__(
        self,
        spec: AgentSpec,
        llm_client: LLMClient,
        prompt_registry: PromptRegistry,
    ) -> None:
        self._spec = spec
        self._llm = llm_client
        self._registry = prompt_registry

    @property
    def name(self) -> str:
        return self._spec.name

    @property
    def spec(self) -> AgentSpec:
        return self._spec

    @abstractmethod
    async def execute(
        self,
        state: dict[str, Any],
        run_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Execute the agent's task given the current run state.

        Returns the agent's output as a dict (validated against output_schema).
        """
        ...

    async def _get_system_prompt(self, channel: str = "promoted") -> str:
        """Resolve the system prompt from the registry."""
        entry = self._registry.get(self._spec.prompt_key, channel=channel)
        if entry is None:
            raise RuntimeError(
                f"No prompt found for key={self._spec.prompt_key!r} channel={channel!r}"
            )
        return entry.body

    async def _call_llm(
        self,
        messages: list[dict[str, Any]],
        system: str | None = None,
        run_id: uuid.UUID | None = None,
        step_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Call the LLM with structured output enforcement and repair loop.

        Implements the bounded repair loop (max 2 retries):
        1. Call model with schema
        2. Validate with Pydantic
        3. On failure: feed back error, retry
        4. After max retries: return error state
        """
        from astraeus_agent_runtime.llm_client import MODEL_ROUTING

        model = MODEL_ROUTING.get(self._spec.model_tier, MODEL_ROUTING["reasoning"])
        schema = self._spec.output_schema.model_json_schema()

        step_id = step_id or uuid.uuid4()
        last_error: str | None = None

        for attempt in range(self._spec.max_retries + 1):
            call_messages = list(messages)

            if last_error and attempt > 0:
                call_messages.append({
                    "role": "user",
                    "content": (
                        f"Your previous output failed validation: {last_error}\n"
                        "Please fix the output to match the required schema."
                    ),
                })

            response = await self._llm.complete(
                messages=call_messages,
                system=system,
                model=model,
                response_schema=schema,
                run_id=run_id,
                step_id=step_id,
                agent_name=self._spec.name,
                prompt_key=self._spec.prompt_key,
            )

            # Parse structured output
            output = response.structured_output
            if output is None:
                # Try parsing content as JSON
                import json
                try:
                    output = json.loads(response.content)
                except (json.JSONDecodeError, ValueError):
                    last_error = "Response is not valid JSON"
                    continue

            # Validate with Pydantic
            try:
                validated = self._spec.output_schema.model_validate(output)
                return validated.model_dump()
            except Exception as e:
                last_error = str(e)
                logger.warning(
                    "schema_repair_attempt",
                    agent=self._spec.name,
                    attempt=attempt + 1,
                    error=last_error,
                )
                continue

        # Repair exhausted
        logger.error(
            "schema_repair_exhausted",
            agent=self._spec.name,
            last_error=last_error,
        )
        return {"error": f"repair_exhausted: {last_error}", "status": "failed"}
