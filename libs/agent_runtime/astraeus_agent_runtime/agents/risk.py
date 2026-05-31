"""Risk agent — wraps Phase 4 risk engine with narrative and HITL triggers."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog

from astraeus_agent_runtime.agents.base import AgentSpec, BaseAgent
from astraeus_agent_runtime.schemas import RiskAssessment
from astraeus_agent_runtime.tools.registry import dispatch_tool

logger = structlog.get_logger("astraeus.agent_runtime.agents.risk")

RISK_SPEC = AgentSpec(
    name="risk",
    prompt_key="risk_agent.system",
    output_schema=RiskAssessment,
    allowed_tools=frozenset(
        {
            "get_portfolio_state",
            "run_risk_check",
            "run_stress_scenario",
            "get_correlation_matrix",
            "get_var_cvar",
        }
    ),
    model_tier="reasoning",
)


class RiskAgent(BaseAgent):
    """Risk agent — evaluates portfolio risk and triggers HITL on breaches."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(spec=RISK_SPEC, **kwargs)

    async def execute(
        self,
        state: dict[str, Any],
        run_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Execute risk assessment."""
        portfolio_id = state.get("metadata", {}).get("portfolio_id", "default")

        # Step 1: Run risk checks
        risk_data = await self._run_checks(portfolio_id, run_id)

        # Step 2: Call LLM for narrative
        system_prompt = await self._get_system_prompt()
        messages = [
            {
                "role": "user",
                "content": (
                    f"Assess risk for portfolio: {portfolio_id}\n\n"
                    f"Risk check results:\n{_format_checks(risk_data)}\n\n"
                    "Provide narrative context for any concerns. "
                    "Set hitl_required=True if any check breaches its threshold."
                ),
            }
        ]

        result = await self._call_llm(messages=messages, system=system_prompt, run_id=run_id)

        if "error" not in result:
            result.setdefault("as_of", datetime.now(tz=UTC).isoformat())
            # Propagate breach detection
            if risk_data.get("any_breach"):
                result["hitl_required"] = True
                result["hitl_reason"] = "Risk check breach detected"

        return result

    async def _run_checks(self, portfolio_id: str, run_id: uuid.UUID | None) -> dict[str, Any]:
        try:
            return await dispatch_tool(
                agent_name="risk",
                tool_name="run_risk_check",
                payload={"portfolio_id": portfolio_id},
                run_id=run_id,
            )
        except Exception as e:
            logger.warning("risk_check_failed", error=str(e))
            return {"checks": [], "any_breach": False}


def _format_checks(risk_data: dict[str, Any]) -> str:
    """Format risk check results for the LLM prompt."""
    checks = risk_data.get("checks", [])
    if not checks:
        return "No risk checks available."

    lines = []
    for check in checks:
        status = "PASS" if check.get("passed") else "BREACH"
        lines.append(
            f"- {check.get('check_name', 'unknown')}: {status} "
            f"(value={check.get('value')}, threshold={check.get('threshold')})"
        )
    return "\n".join(lines)
