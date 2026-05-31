"""Recommendation lifecycle state machine.

Valid transitions:
    proposed  → approved | rejected | overridden | expired
    approved  → (terminal)
    rejected  → (terminal)
    overridden → (terminal)
    expired   → (terminal)
"""

from __future__ import annotations

from .contracts import DecisionType, RecommendationState

# Allowed transitions: current_state -> set of valid next states
_TRANSITIONS: dict[RecommendationState, set[RecommendationState]] = {
    RecommendationState.PROPOSED: {
        RecommendationState.APPROVED,
        RecommendationState.REJECTED,
        RecommendationState.OVERRIDDEN,
        RecommendationState.EXPIRED,
    },
    RecommendationState.APPROVED: set(),
    RecommendationState.REJECTED: set(),
    RecommendationState.OVERRIDDEN: set(),
    RecommendationState.EXPIRED: set(),
}

# Decision type → resulting state
_DECISION_MAP: dict[DecisionType, RecommendationState] = {
    DecisionType.APPROVE: RecommendationState.APPROVED,
    DecisionType.REJECT: RecommendationState.REJECTED,
    DecisionType.OVERRIDE: RecommendationState.OVERRIDDEN,
}


class InvalidTransitionError(Exception):
    """Raised when a state transition is not allowed."""

    def __init__(self, current: RecommendationState, target: RecommendationState) -> None:
        self.current = current
        self.target = target
        super().__init__(f"Cannot transition from {current} to {target}")


def transition(current: RecommendationState, decision: DecisionType) -> RecommendationState:
    """Apply a decision to the current state, returning the new state.

    Raises InvalidTransitionError if the transition is not allowed.
    """
    target = _DECISION_MAP[decision]
    if target not in _TRANSITIONS[current]:
        raise InvalidTransitionError(current, target)
    return target


def expire(current: RecommendationState) -> RecommendationState:
    """Expire a recommendation (only valid from proposed state)."""
    target = RecommendationState.EXPIRED
    if target not in _TRANSITIONS[current]:
        raise InvalidTransitionError(current, target)
    return target


def is_terminal(state: RecommendationState) -> bool:
    """Check if a state is terminal (no further transitions allowed)."""
    return len(_TRANSITIONS[state]) == 0
