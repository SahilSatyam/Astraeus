"""Orchestrator — LangGraph state graph for agent workflows.

Uses LangGraph as a thin state-machine layer. We do NOT use LangChain's
Agent, AgentExecutor, Tool, or Chain primitives. Only:
- langgraph.graph.StateGraph
- Checkpointer (Postgres in production)
- Interrupt API (for HITL)

The orchestrator is the facade that a future framework swap touches.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog

from astraeus_agent_runtime.hitl import HITLQueue, HITLTrigger
from astraeus_agent_runtime.llm_client import LLMClient
from astraeus_agent_runtime.metrics import record_run_complete, record_step_complete
from astraeus_agent_runtime.prompt_registry import PromptRegistry, create_default_registry
from astraeus_agent_runtime.state import AgentState, RunMetadata
from astraeus_agent_runtime.tools.implementations import register_all_tools
from langgraph.graph import StateGraph, END

logger = structlog.get_logger("astraeus.agent_runtime.orchestrator")


class WorkflowOrchestrator:
    """Orchestrates multi-agent workflows as state graphs.

    Supported workflows:
    - trade_thesis: Research → Sentiment → Strategy → Risk → Compliance
    - daily_brief: Research → Sentiment → Risk → Compliance
    - portfolio_commentary: Sentiment → Strategy → Risk → Portfolio → Compliance
    - risk_drilldown: Risk → Portfolio → Compliance
    """

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        prompt_registry: PromptRegistry | None = None,
        hitl_queue: HITLQueue | None = None,
    ) -> None:
        self._llm = llm_client or LLMClient()
        self._registry = prompt_registry or create_default_registry()
        self._hitl = hitl_queue or HITLQueue()
        self._runs: dict[uuid.UUID, dict[str, Any]] = {}

        # Register tools on init
        register_all_tools()

    async def run_workflow(
        self,
        workflow: str,
        inputs: dict[str, Any],
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a workflow end-to-end.

        Args:
            workflow: Workflow key (trade_thesis, daily_brief, etc.)
            inputs: Workflow-specific inputs (ticker, lookback_days, etc.)
            options: Runtime options (channel, max_cost_usd, timeout_s).

        Returns:
            Run result with status, output, cost, and duration.
        """
        options = options or {}
        metadata = RunMetadata(
            workflow_key=workflow,
            ticker=inputs.get("ticker"),
            channel=options.get("channel", "promoted"),
            max_cost_usd=options.get("max_cost_usd", 1.0),
            timeout_s=options.get("timeout_s", 120),
            mode=options.get("mode", "production"),
        )

        run_id = metadata.run_id
        start = time.perf_counter()

        # Initialize state
        state: AgentState = {
            "metadata": metadata.model_dump(mode="json"),
            "ticker": inputs.get("ticker", ""),
            "lookback_days": inputs.get("lookback_days", 30),
            "focus": inputs.get("focus", ""),
            "steps": [],
            "total_cost_usd": 0.0,
            "total_duration_ms": 0.0,
            "hitl_required": False,
            "hitl_reason": "",
            "error": "",
            "status": "running",
        }

        # Store run
        self._runs[run_id] = {
            "run_id": str(run_id),
            "workflow_key": workflow,
            "status": "running",
            "inputs": inputs,
            "output": None,
            "cost_usd": 0.0,
            "duration_ms": 0,
            "created_at": datetime.now(tz=UTC).isoformat(),
        }

        try:
            # Get workflow steps
            steps = self._get_workflow_steps(workflow)

            # Build StateGraph
            workflow_graph = StateGraph(AgentState)

            # Add nodes
            for step_name in steps:
                workflow_graph.add_node(step_name, self._create_node(step_name, run_id, workflow))

            # Add edges
            for i in range(len(steps) - 1):
                # If HITL triggered, route to END instead of next node
                def _route(state: AgentState) -> str:
                    if state.get("hitl_required") or state.get("status") == "failed":
                        return END
                    return steps[i + 1]

                workflow_graph.add_conditional_edges(steps[i], _route)

            workflow_graph.set_entry_point(steps[0])
            app = workflow_graph.compile()

            # Execute graph
            final_state = await app.ainvoke(state)
            state.update(final_state)

            # Finalize
            duration_ms = (time.perf_counter() - start) * 1000
            state["total_duration_ms"] = duration_ms

            if state["status"] == "running":
                state["status"] = "hitl_pending" if state["hitl_required"] else "completed"

        except Exception as e:
            state["status"] = "failed"
            state["error"] = str(e)
            logger.error("workflow_failed", run_id=str(run_id), error=str(e))

        # Build final output
        duration_ms = (time.perf_counter() - start) * 1000
        run_result = {
            "run_id": str(run_id),
            "workflow_key": workflow,
            "status": state["status"],
            "output": self._build_workflow_output(workflow, state),
            "cost_usd": round(state["total_cost_usd"], 6),
            "duration_ms": round(duration_ms, 1),
            "hitl_required": state["hitl_required"],
            "hitl_reason": state["hitl_reason"],
            "steps": state["steps"],
            "error": state.get("error", ""),
        }

        self._runs[run_id] = run_result
        record_run_complete(run_result)
        return run_result

    def get_run(self, run_id: uuid.UUID) -> dict[str, Any] | None:
        """Get a run by ID."""
        return self._runs.get(run_id)

    def _get_workflow_steps(self, workflow: str) -> list[str]:
        """Get the ordered agent steps for a workflow."""
        workflows: dict[str, list[str]] = {
            "trade_thesis": ["research", "sentiment", "strategy", "risk", "compliance"],
            "daily_brief": ["research", "sentiment", "risk", "compliance"],
            "portfolio_commentary": ["sentiment", "strategy", "risk", "portfolio", "compliance"],
            "risk_drilldown": ["risk", "portfolio", "compliance"],
        }
        steps = workflows.get(workflow)
        if steps is None:
            raise ValueError(f"Unknown workflow: {workflow!r}. Available: {list(workflows.keys())}")
        return steps

    def _create_node(self, step_name: str, run_id: uuid.UUID, workflow: str) -> Any:
        """Create a LangGraph node function for a specific step."""
        async def node(state: AgentState) -> dict[str, Any]:
            step_start = time.perf_counter()
            step_id = uuid.uuid4()
            logger.info("step_start", run_id=str(run_id), step=step_name)

            agent = self._create_agent(step_name)
            step_output = await agent.execute(state, run_id=run_id)

            step_duration = (time.perf_counter() - step_start) * 1000
            
            updates: dict[str, Any] = {}
            steps_list = state.get("steps", []).copy()
            steps_list.append(
                {
                    "step_id": str(step_id),
                    "agent_name": step_name,
                    "status": "error" if "error" in step_output else "completed",
                    "duration_ms": round(step_duration, 1),
                }
            )
            updates["steps"] = steps_list
            updates[f"{step_name}_output"] = step_output

            record_step_complete(step_name, step_duration)

            if step_output.get("hitl_required"):
                updates["hitl_required"] = True
                updates["hitl_reason"] = step_output.get("hitl_reason", f"{step_name} triggered HITL")
                
                self._hitl.submit(
                    run_id=run_id,
                    workflow_key=workflow,
                    triggered_by=HITLTrigger.RISK_BREACH,
                    reason={"agent": step_name, "detail": updates["hitl_reason"]},
                    agent_state=dict(state),
                    candidate_output=step_output,
                )
                logger.warning(
                    "hitl_triggered",
                    run_id=str(run_id),
                    agent=step_name,
                    reason=updates["hitl_reason"],
                )

            metadata = RunMetadata(**state.get("metadata", {}))
            step_cost = sum(
                r.cost_usd
                for r in self._llm.call_records
                if r.run_id == run_id and r.step_id == step_id
            )
            updates["total_cost_usd"] = state.get("total_cost_usd", 0.0) + step_cost

            if updates["total_cost_usd"] > metadata.max_cost_usd:
                updates["status"] = "failed"
                updates["error"] = f"Cost overrun: ${updates['total_cost_usd']:.4f} > ${metadata.max_cost_usd}"

            return updates

        return node

    def _create_agent(self, agent_name: str) -> Any:
        """Create an agent instance by name."""
        from astraeus_agent_runtime.agents.compliance import ComplianceAgent
        from astraeus_agent_runtime.agents.execution import ExecutionAgent
        from astraeus_agent_runtime.agents.portfolio import PortfolioAgent
        from astraeus_agent_runtime.agents.research import ResearchAgent
        from astraeus_agent_runtime.agents.risk import RiskAgent
        from astraeus_agent_runtime.agents.sentiment import SentimentAgent
        from astraeus_agent_runtime.agents.strategy import StrategyAgent

        agents: dict[str, type] = {
            "research": ResearchAgent,
            "sentiment": SentimentAgent,
            "strategy": StrategyAgent,
            "risk": RiskAgent,
            "portfolio": PortfolioAgent,
            "execution": ExecutionAgent,
            "compliance": ComplianceAgent,
        }

        agent_cls = agents.get(agent_name)
        if agent_cls is None:
            raise ValueError(f"Unknown agent: {agent_name!r}")

        return agent_cls(llm_client=self._llm, prompt_registry=self._registry)

    def _build_workflow_output(self, workflow: str, state: AgentState) -> dict[str, Any] | None:
        """Build the composite workflow output from agent states."""
        if state.get("status") == "failed":
            return None

        output: dict[str, Any] = {
            "workflow": workflow,
            "ticker": state.get("ticker", ""),
            "as_of": datetime.now(tz=UTC).isoformat(),
        }

        # Include all agent outputs
        for key in (
            "research_output",
            "sentiment_output",
            "strategy_output",
            "risk_output",
            "portfolio_output",
            "execution_output",
            "compliance_output",
        ):
            value = state.get(key)  # type: ignore[literal-required]
            if value:
                output[key.replace("_output", "")] = value

        return output
