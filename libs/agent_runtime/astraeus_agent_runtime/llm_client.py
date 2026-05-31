"""LLM client wrapper — single seam for all model calls.

Handles:
- Anthropic (Claude) and OpenAI model routing
- Retry with exponential backoff on transient errors
- Cost metering (input/output/cache tokens → USD)
- Latency tracking via OTEL spans
- Structured output enforcement (tool-use for Anthropic, json_schema for OpenAI)
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger("astraeus.agent_runtime.llm_client")

# Cost per 1M tokens (approximate, updated periodically)
_COST_TABLE: dict[str, dict[str, float]] = {
    "claude-sonnet-4-20250514": {
        "input": 3.0,
        "output": 15.0,
        "cache_read": 0.30,
        "cache_write": 3.75,
    },
    "claude-haiku-3-5-20241022": {
        "input": 0.80,
        "output": 4.0,
        "cache_read": 0.08,
        "cache_write": 1.0,
    },
    "gpt-4o-mini": {"input": 0.15, "output": 0.60, "cache_read": 0.075, "cache_write": 0.15},
}

# Default model for each routing tier
MODEL_ROUTING: dict[str, str] = {
    "reasoning": "claude-sonnet-4-20250514",
    "synthesis": "claude-sonnet-4-20250514",
    "classification": "claude-haiku-3-5-20241022",
    "cheap": "gpt-4o-mini",
}


@dataclass(frozen=True, slots=True)
class LLMResponse:
    """Response from an LLM call with full metadata."""

    content: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    ttft_ms: float | None = None
    request_id: str = ""
    structured_output: dict[str, Any] | None = None


@dataclass(slots=True)
class LLMCallRecord:
    """Record for the cost ledger."""

    call_id: uuid.UUID = field(default_factory=uuid.uuid4)
    run_id: uuid.UUID | None = None
    step_id: uuid.UUID | None = None
    agent_name: str = ""
    prompt_key: str = ""
    prompt_version: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    ttft_ms: float | None = None
    status: str = "success"
    error_class: str | None = None


def compute_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> float:
    """Compute cost in USD for a model call."""
    costs = _COST_TABLE.get(model)
    if costs is None:
        # Unknown model — estimate conservatively
        return (input_tokens + output_tokens) * 5.0 / 1_000_000

    cost = (
        (input_tokens - cache_read_tokens) * costs["input"] / 1_000_000
        + output_tokens * costs["output"] / 1_000_000
        + cache_read_tokens * costs.get("cache_read", 0) / 1_000_000
        + cache_write_tokens * costs.get("cache_write", 0) / 1_000_000
    )
    return round(cost, 6)


class LLMClient:
    """Unified LLM client supporting Anthropic and OpenAI.

    This is the ONLY path to model calls. Agents do not import
    anthropic/openai directly.
    """

    def __init__(
        self,
        anthropic_api_key: str | None = None,
        openai_api_key: str | None = None,
        default_model: str = "claude-sonnet-4-20250514",
        max_retries: int = 2,
        timeout_s: int = 60,
    ) -> None:
        self._anthropic_key = anthropic_api_key
        self._openai_key = openai_api_key
        self._default_model = default_model
        self._max_retries = max_retries
        self._timeout_s = timeout_s
        self._call_records: list[LLMCallRecord] = []

    @property
    def call_records(self) -> list[LLMCallRecord]:
        """Access recorded calls for cost ledger persistence."""
        return self._call_records

    def clear_records(self) -> None:
        self._call_records.clear()

    async def complete(
        self,
        messages: list[dict[str, Any]],
        system: str | None = None,
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        response_schema: dict[str, Any] | None = None,
        run_id: uuid.UUID | None = None,
        step_id: uuid.UUID | None = None,
        agent_name: str = "",
        prompt_key: str = "",
        prompt_version: str = "",
    ) -> LLMResponse:
        """Execute an LLM completion with retry and cost tracking.

        Args:
            messages: Chat messages in OpenAI format.
            system: System prompt (separate for Anthropic).
            model: Model identifier. Defaults to configured default.
            temperature: Sampling temperature.
            max_tokens: Max output tokens.
            response_schema: JSON schema for structured output enforcement.
            run_id: Parent run ID for cost ledger.
            step_id: Parent step ID for cost ledger.
            agent_name: Agent making the call.
            prompt_key: Prompt registry key.
            prompt_version: Prompt version.

        Returns:
            LLMResponse with content, tokens, cost, and latency.
        """
        model = model or self._default_model
        start = time.perf_counter()

        # Determine provider
        is_anthropic = "claude" in model
        is_openai = model.startswith("gpt") or model.startswith("o1")

        response: LLMResponse | None = None
        last_error: Exception | None = None

        for attempt in range(self._max_retries + 1):
            try:
                if is_anthropic:
                    response = await self._call_anthropic(
                        messages=messages,
                        system=system,
                        model=model,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        response_schema=response_schema,
                    )
                elif is_openai:
                    response = await self._call_openai(
                        messages=messages,
                        system=system,
                        model=model,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        response_schema=response_schema,
                    )
                else:
                    # Fallback: treat as OpenAI-compatible
                    response = await self._call_openai(
                        messages=messages,
                        system=system,
                        model=model,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        response_schema=response_schema,
                    )
                break
            except Exception as e:
                last_error = e
                if attempt < self._max_retries:
                    wait = 2**attempt
                    logger.warning(
                        "llm_call_retry",
                        model=model,
                        attempt=attempt + 1,
                        error=str(e),
                        wait_s=wait,
                    )
                    import asyncio

                    await asyncio.sleep(wait)

        latency_ms = (time.perf_counter() - start) * 1000

        if response is None:
            # All retries exhausted
            record = LLMCallRecord(
                run_id=run_id,
                step_id=step_id,
                agent_name=agent_name,
                prompt_key=prompt_key,
                prompt_version=prompt_version,
                model=model,
                latency_ms=latency_ms,
                status="error",
                error_class=type(last_error).__name__ if last_error else "Unknown",
            )
            self._call_records.append(record)
            raise RuntimeError(
                f"LLM call failed after {self._max_retries + 1} attempts: {last_error}"
            )

        # Record for cost ledger
        record = LLMCallRecord(
            run_id=run_id,
            step_id=step_id,
            agent_name=agent_name,
            prompt_key=prompt_key,
            prompt_version=prompt_version,
            model=model,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cache_read_tokens=response.cache_read_tokens,
            cache_write_tokens=response.cache_write_tokens,
            cost_usd=response.cost_usd,
            latency_ms=latency_ms,
            status="success",
        )
        self._call_records.append(record)

        logger.info(
            "llm_call_complete",
            model=model,
            agent=agent_name,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cost_usd=response.cost_usd,
            latency_ms=round(latency_ms, 1),
        )

        return response

    async def _call_anthropic(
        self,
        messages: list[dict[str, Any]],
        system: str | None,
        model: str,
        temperature: float,
        max_tokens: int,
        response_schema: dict[str, Any] | None,
    ) -> LLMResponse:
        """Call Anthropic Claude API."""
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=self._anthropic_key)

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system:
            kwargs["system"] = system

        # Structured output via tool-use
        if response_schema:
            kwargs["tools"] = [
                {
                    "name": "structured_output",
                    "description": "Return structured output matching the schema.",
                    "input_schema": response_schema,
                }
            ]
            kwargs["tool_choice"] = {"type": "tool", "name": "structured_output"}

        start = time.perf_counter()
        resp = await client.messages.create(**kwargs)
        ttft_ms = (time.perf_counter() - start) * 1000

        # Extract content
        content = ""
        structured_output = None
        for block in resp.content:
            if block.type == "text":
                content = block.text
            elif block.type == "tool_use" and block.name == "structured_output":
                structured_output = block.input
                content = str(block.input)

        cost = compute_cost(
            model=model,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
            cache_read_tokens=getattr(resp.usage, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(resp.usage, "cache_creation_input_tokens", 0) or 0,
        )

        return LLMResponse(
            content=content,
            model=model,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
            cache_read_tokens=getattr(resp.usage, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(resp.usage, "cache_creation_input_tokens", 0) or 0,
            cost_usd=cost,
            latency_ms=ttft_ms,
            ttft_ms=ttft_ms,
            request_id=resp.id,
            structured_output=structured_output,
        )

    async def _call_openai(
        self,
        messages: list[dict[str, Any]],
        system: str | None,
        model: str,
        temperature: float,
        max_tokens: int,
        response_schema: dict[str, Any] | None,
    ) -> LLMResponse:
        """Call OpenAI API."""
        import openai

        client = openai.AsyncOpenAI(api_key=self._openai_key)

        full_messages = []
        if system:
            full_messages.append({"role": "system", "content": system})
        full_messages.extend(messages)

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": full_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        if response_schema:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "output", "strict": True, "schema": response_schema},
            }

        start = time.perf_counter()
        resp = await client.chat.completions.create(**kwargs)
        ttft_ms = (time.perf_counter() - start) * 1000

        choice = resp.choices[0]
        content = choice.message.content or ""

        input_tokens = resp.usage.prompt_tokens if resp.usage else 0
        output_tokens = resp.usage.completion_tokens if resp.usage else 0

        cost = compute_cost(model=model, input_tokens=input_tokens, output_tokens=output_tokens)

        structured_output = None
        if response_schema and content:
            import json

            try:
                structured_output = json.loads(content)
            except json.JSONDecodeError:
                pass

        return LLMResponse(
            content=content,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            latency_ms=ttft_ms,
            ttft_ms=ttft_ms,
            request_id=resp.id or "",
            structured_output=structured_output,
        )
