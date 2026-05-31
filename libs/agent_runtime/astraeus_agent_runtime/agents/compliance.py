"""Compliance agent — final gate before output is surfaced to humans."""

from __future__ import annotations

import uuid
from typing import Any

import structlog

from astraeus_agent_runtime.agents.base import AgentSpec, BaseAgent
from astraeus_agent_runtime.guardrails import validate_citations
from astraeus_agent_runtime.schemas import ComplianceResult

logger = structlog.get_logger("astraeus.agent_runtime.agents.compliance")

COMPLIANCE_SPEC = AgentSpec(
    name="compliance",
    prompt_key="compliance_agent.system",
    output_schema=ComplianceResult,
    allowed_tools=frozenset(
        {
            "lookup_restricted_list",
            "lookup_policy_rule",
            "write_audit_envelope",
        }
    ),
    model_tier="classification",
)


class ComplianceAgent(BaseAgent):
    """Compliance agent — reviews and gates all agent outputs."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(spec=COMPLIANCE_SPEC, **kwargs)

    async def execute(
        self,
        state: dict[str, Any],
        run_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Review the accumulated agent outputs for compliance."""
        flags: list[str] = []
        redactions: list[str] = []

        # Check research output citations
        research = state.get("research_output", {})
        if research and "error" not in research:
            citation_check = validate_citations(research)
            if not citation_check.passed:
                flags.extend(citation_check.flags)

        # Check for risk breaches requiring HITL
        risk = state.get("risk_output", {})
        if risk and risk.get("hitl_required"):
            flags.append("risk_breach_requires_hitl")

        # Determine approval
        approved = len(flags) == 0

        # For non-trivial cases, call LLM for nuanced review
        if flags:
            system_prompt = await self._get_system_prompt()
            messages = [
                {
                    "role": "user",
                    "content": (
                        f"Review the following agent outputs for compliance.\n\n"
                        f"Flags detected: {flags}\n\n"
                        f"Research output present: {bool(research)}\n"
                        f"Risk output present: {bool(risk)}\n\n"
                        "Determine if these outputs can be approved or need intervention."
                    ),
                }
            ]
            result = await self._call_llm(messages=messages, system=system_prompt, run_id=run_id)
            if "error" not in result:
                return result

        return ComplianceResult(
            approved=approved,
            flags=flags,
            redactions_applied=redactions,
            audit_notes=f"Automated review: {'approved' if approved else 'flagged'}",
        ).model_dump()
