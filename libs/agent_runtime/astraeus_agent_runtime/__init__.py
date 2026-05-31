"""Astraeus AI Agent Runtime — multi-agent orchestration with structured outputs.

Key principles:
- Agents augment analysts. Agents never autonomously trade.
- Every output is schema-valid (Pydantic) with mandatory citations.
- All prompts, tool calls, and costs are observable and replayable.
- HITL queue gates any action that mutates platform state.
"""
