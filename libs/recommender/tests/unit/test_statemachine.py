"""Tests for the recommendation lifecycle state machine."""

import pytest
from astraeus_recommender.contracts import DecisionType, RecommendationState
from astraeus_recommender.statemachine import (
    InvalidTransitionError,
    expire,
    is_terminal,
    transition,
)


class TestTransition:
    """Test valid and invalid state transitions."""

    def test_approve_from_proposed(self):
        result = transition(RecommendationState.PROPOSED, DecisionType.APPROVE)
        assert result == RecommendationState.APPROVED

    def test_reject_from_proposed(self):
        result = transition(RecommendationState.PROPOSED, DecisionType.REJECT)
        assert result == RecommendationState.REJECTED

    def test_override_from_proposed(self):
        result = transition(RecommendationState.PROPOSED, DecisionType.OVERRIDE)
        assert result == RecommendationState.OVERRIDDEN

    def test_cannot_approve_from_approved(self):
        with pytest.raises(InvalidTransitionError):
            transition(RecommendationState.APPROVED, DecisionType.APPROVE)

    def test_cannot_reject_from_rejected(self):
        with pytest.raises(InvalidTransitionError):
            transition(RecommendationState.REJECTED, DecisionType.REJECT)

    def test_cannot_override_from_expired(self):
        with pytest.raises(InvalidTransitionError):
            transition(RecommendationState.EXPIRED, DecisionType.OVERRIDE)


class TestExpire:
    """Test expiration transitions."""

    def test_expire_from_proposed(self):
        result = expire(RecommendationState.PROPOSED)
        assert result == RecommendationState.EXPIRED

    def test_cannot_expire_from_approved(self):
        with pytest.raises(InvalidTransitionError):
            expire(RecommendationState.APPROVED)


class TestIsTerminal:
    """Test terminal state detection."""

    def test_proposed_not_terminal(self):
        assert not is_terminal(RecommendationState.PROPOSED)

    def test_approved_is_terminal(self):
        assert is_terminal(RecommendationState.APPROVED)

    def test_rejected_is_terminal(self):
        assert is_terminal(RecommendationState.REJECTED)

    def test_overridden_is_terminal(self):
        assert is_terminal(RecommendationState.OVERRIDDEN)

    def test_expired_is_terminal(self):
        assert is_terminal(RecommendationState.EXPIRED)
