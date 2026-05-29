"""Unit tests for correlation clustering and concentration metrics."""

from __future__ import annotations

from decimal import Decimal

import numpy as np
import pytest
from astraeus_portfolio.contracts import ClusterReport
from astraeus_portfolio.risk.clustering import (
    _compute_correlation_matrix,
    _compute_effective_n_bets,
    _compute_herfindahl_index,
    _compute_max_cluster_weight,
    _correlation_to_distance,
    _pearson_correlation,
    _ward_clustering,
    compute_cluster_report,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def rng() -> np.random.Generator:
    return np.random.default_rng(42)


@pytest.fixture
def simple_returns(rng: np.random.Generator) -> np.ndarray:
    """Generate a valid T×n return matrix (T=300, n=5) with no NaN."""
    return rng.standard_normal((300, 5)) * 0.01


@pytest.fixture
def simple_weights() -> np.ndarray:
    """Equal-weight portfolio for 5 assets."""
    return np.array([0.2, 0.2, 0.2, 0.2, 0.2])


@pytest.fixture
def simple_covariance(simple_returns: np.ndarray) -> np.ndarray:
    """Sample covariance from simple_returns."""
    return np.cov(simple_returns, rowvar=False)


@pytest.fixture
def simple_symbols() -> list[str]:
    return ["AAPL", "MSFT", "GOOG", "AMZN", "META"]


# ---------------------------------------------------------------------------
# Tests: _pearson_correlation
# ---------------------------------------------------------------------------


class TestPearsonCorrelation:
    """Tests for the internal Pearson correlation helper."""

    def test_perfect_positive_correlation(self) -> None:
        x = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        y = np.array([2.0, 4.0, 6.0, 8.0, 10.0])
        assert abs(_pearson_correlation(x, y) - 1.0) < 1e-10

    def test_perfect_negative_correlation(self) -> None:
        x = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        y = np.array([10.0, 8.0, 6.0, 4.0, 2.0])
        assert abs(_pearson_correlation(x, y) - (-1.0)) < 1e-10

    def test_zero_variance_returns_zero(self) -> None:
        x = np.array([1.0, 1.0, 1.0, 1.0])
        y = np.array([1.0, 2.0, 3.0, 4.0])
        assert _pearson_correlation(x, y) == 0.0

    def test_uncorrelated_near_zero(self, rng: np.random.Generator) -> None:
        x = rng.standard_normal(10000)
        y = rng.standard_normal(10000)
        rho = _pearson_correlation(x, y)
        assert abs(rho) < 0.05  # Should be near zero for large samples


# ---------------------------------------------------------------------------
# Tests: _correlation_to_distance
# ---------------------------------------------------------------------------


class TestCorrelationToDistance:
    """Tests for correlation-to-distance conversion."""

    def test_perfect_correlation_zero_distance(self) -> None:
        corr = np.array([[1.0, 1.0], [1.0, 1.0]])
        dist = _correlation_to_distance(corr)
        assert dist[0, 1] == pytest.approx(0.0, abs=1e-10)

    def test_zero_correlation_distance(self) -> None:
        corr = np.array([[1.0, 0.0], [0.0, 1.0]])
        dist = _correlation_to_distance(corr)
        expected = np.sqrt(0.5)
        assert dist[0, 1] == pytest.approx(expected, abs=1e-10)

    def test_negative_correlation_max_distance(self) -> None:
        corr = np.array([[1.0, -1.0], [-1.0, 1.0]])
        dist = _correlation_to_distance(corr)
        expected = np.sqrt(1.0)  # sqrt(0.5 * (1 - (-1))) = sqrt(1) = 1
        assert dist[0, 1] == pytest.approx(expected, abs=1e-10)

    def test_diagonal_is_zero(self) -> None:
        corr = np.array([[1.0, 0.5], [0.5, 1.0]])
        dist = _correlation_to_distance(corr)
        assert dist[0, 0] == 0.0
        assert dist[1, 1] == 0.0

    def test_symmetry(self) -> None:
        corr = np.array([[1.0, 0.3, 0.7], [0.3, 1.0, 0.5], [0.7, 0.5, 1.0]])
        dist = _correlation_to_distance(corr)
        np.testing.assert_allclose(dist, dist.T, atol=1e-14)


# ---------------------------------------------------------------------------
# Tests: _ward_clustering
# ---------------------------------------------------------------------------


class TestWardClustering:
    """Tests for Ward linkage clustering."""

    def test_returns_correct_number_of_clusters(self) -> None:
        # 10 assets, request 3 clusters
        rng = np.random.default_rng(42)
        corr = np.corrcoef(rng.standard_normal((100, 10)), rowvar=False)
        dist = _correlation_to_distance(corr)
        labels = _ward_clustering(dist, k=3)
        assert len(np.unique(labels)) <= 3

    def test_labels_are_zero_indexed(self) -> None:
        rng = np.random.default_rng(42)
        corr = np.corrcoef(rng.standard_normal((100, 10)), rowvar=False)
        dist = _correlation_to_distance(corr)
        labels = _ward_clustering(dist, k=3)
        assert labels.min() == 0

    def test_all_assets_assigned(self) -> None:
        rng = np.random.default_rng(42)
        n = 10
        corr = np.corrcoef(rng.standard_normal((100, n)), rowvar=False)
        dist = _correlation_to_distance(corr)
        labels = _ward_clustering(dist, k=3)
        assert len(labels) == n

    def test_two_assets_two_clusters(self) -> None:
        # Two uncorrelated assets should form 2 clusters
        dist = np.array([[0.0, 0.7], [0.7, 0.0]])
        labels = _ward_clustering(dist, k=2)
        assert len(np.unique(labels)) == 2


# ---------------------------------------------------------------------------
# Tests: _compute_max_cluster_weight
# ---------------------------------------------------------------------------


class TestMaxClusterWeight:
    """Tests for max cluster weight computation."""

    def test_single_cluster_all_weight(self) -> None:
        weights = np.array([0.3, 0.3, 0.4])
        labels = np.array([0, 0, 0])
        result = _compute_max_cluster_weight(weights, labels)
        assert result == pytest.approx(1.0, abs=1e-10)

    def test_equal_weight_two_clusters(self) -> None:
        weights = np.array([0.25, 0.25, 0.25, 0.25])
        labels = np.array([0, 0, 1, 1])
        result = _compute_max_cluster_weight(weights, labels)
        assert result == pytest.approx(0.5, abs=1e-10)

    def test_uses_absolute_weights(self) -> None:
        weights = np.array([0.5, -0.5])
        labels = np.array([0, 1])
        result = _compute_max_cluster_weight(weights, labels)
        assert result == pytest.approx(0.5, abs=1e-10)


# ---------------------------------------------------------------------------
# Tests: _compute_herfindahl_index
# ---------------------------------------------------------------------------


class TestHerfindahlIndex:
    """Tests for Herfindahl index computation."""

    def test_single_cluster_hhi_is_one(self) -> None:
        weights = np.array([0.5, 0.5])
        labels = np.array([0, 0])
        result = _compute_herfindahl_index(weights, labels)
        assert result == pytest.approx(1.0, abs=1e-10)

    def test_equal_weight_equal_clusters(self) -> None:
        # 4 assets, equal weight, 4 clusters -> each cluster weight = 0.25
        # HHI = 4 * 0.25^2 = 0.25
        weights = np.array([0.25, 0.25, 0.25, 0.25])
        labels = np.array([0, 1, 2, 3])
        result = _compute_herfindahl_index(weights, labels)
        assert result == pytest.approx(0.25, abs=1e-10)

    def test_concentrated_portfolio(self) -> None:
        # One cluster has 90% weight, another has 10%
        weights = np.array([0.45, 0.45, 0.05, 0.05])
        labels = np.array([0, 0, 1, 1])
        # Cluster 0 weight = 0.9, Cluster 1 weight = 0.1
        # HHI = 0.9^2 + 0.1^2 = 0.81 + 0.01 = 0.82
        result = _compute_herfindahl_index(weights, labels)
        assert result == pytest.approx(0.82, abs=1e-10)


# ---------------------------------------------------------------------------
# Tests: _compute_effective_n_bets
# ---------------------------------------------------------------------------


class TestEffectiveNBets:
    """Tests for Effective Number of Bets computation."""

    def test_single_asset_returns_one(self) -> None:
        weights = np.array([1.0])
        cov = np.array([[0.04]])
        labels = np.array([0])
        result = _compute_effective_n_bets(weights, cov, labels)
        assert result == pytest.approx(1.0, abs=1e-8)

    def test_two_uncorrelated_equal_weight_enb_gt_one(self) -> None:
        # Two uncorrelated assets with equal weight
        weights = np.array([0.5, 0.5])
        cov = np.array([[0.04, 0.0], [0.0, 0.04]])
        labels = np.array([0, 1])
        result = _compute_effective_n_bets(weights, cov, labels)
        # Each cluster contributes equally -> ENB = 2
        assert result == pytest.approx(2.0, abs=1e-8)

    def test_multi_asset_enb_greater_than_one(self) -> None:
        """If portfolio has > 1 asset with non-zero weight, ENB > 1.0."""
        rng = np.random.default_rng(42)
        n = 5
        weights = np.array([0.2, 0.2, 0.2, 0.2, 0.2])
        # Generate a valid PSD covariance
        A = rng.standard_normal((100, n))
        cov = np.cov(A, rowvar=False)
        labels = np.array([0, 1, 2, 3, 4])
        result = _compute_effective_n_bets(weights, cov, labels)
        assert result > 1.0

    def test_zero_variance_returns_one(self) -> None:
        weights = np.array([0.5, 0.5])
        cov = np.zeros((2, 2))
        labels = np.array([0, 1])
        result = _compute_effective_n_bets(weights, cov, labels)
        assert result == 1.0


# ---------------------------------------------------------------------------
# Tests: _compute_correlation_matrix
# ---------------------------------------------------------------------------


class TestComputeCorrelationMatrix:
    """Tests for correlation matrix computation with overlap filtering."""

    def test_no_nan_full_overlap(self, rng: np.random.Generator) -> None:
        returns = rng.standard_normal((300, 3)) * 0.01
        symbols = ["A", "B", "C"]
        corr, excluded = _compute_correlation_matrix(returns, symbols, window=252, min_overlap=60)
        assert excluded == []
        assert corr.shape == (3, 3)
        # Diagonal should be 1
        np.testing.assert_allclose(np.diag(corr), 1.0, atol=1e-10)

    def test_insufficient_overlap_excludes_pair(self) -> None:
        # Create returns where pair (0, 1) has < 60 overlapping days
        returns = np.full((300, 3), np.nan)
        # Asset 0: data in rows 0-99
        returns[0:100, 0] = np.random.default_rng(1).standard_normal(100) * 0.01
        # Asset 1: data in rows 200-299 (no overlap with asset 0)
        returns[200:300, 1] = np.random.default_rng(2).standard_normal(100) * 0.01
        # Asset 2: data in rows 0-299 (full overlap with both)
        returns[:, 2] = np.random.default_rng(3).standard_normal(300) * 0.01

        symbols = ["A", "B", "C"]
        corr, excluded = _compute_correlation_matrix(returns, symbols, window=252, min_overlap=60)
        # Pair (A, B) should be excluded
        assert ("A", "B") in excluded
        # Correlation for excluded pair should be 0
        assert corr[0, 1] == 0.0
        assert corr[1, 0] == 0.0

    def test_uses_last_window_rows(self) -> None:
        rng = np.random.default_rng(42)
        # 500 rows, window=252 -> uses last 252 rows
        returns = rng.standard_normal((500, 2)) * 0.01
        symbols = ["A", "B"]
        corr, _ = _compute_correlation_matrix(returns, symbols, window=252, min_overlap=60)
        # Manually compute correlation on last 252 rows
        data = returns[-252:, :]
        expected_corr = np.corrcoef(data, rowvar=False)[0, 1]
        assert corr[0, 1] == pytest.approx(expected_corr, abs=1e-10)


# ---------------------------------------------------------------------------
# Tests: compute_cluster_report (integration)
# ---------------------------------------------------------------------------


class TestComputeClusterReport:
    """Integration tests for the full compute_cluster_report function."""

    def test_returns_cluster_report(
        self,
        simple_returns: np.ndarray,
        simple_weights: np.ndarray,
        simple_covariance: np.ndarray,
        simple_symbols: list[str],
    ) -> None:
        result = compute_cluster_report(
            simple_returns, simple_weights, simple_covariance, simple_symbols
        )
        assert isinstance(result, ClusterReport)

    def test_cluster_assignments_cover_all_symbols(
        self,
        simple_returns: np.ndarray,
        simple_weights: np.ndarray,
        simple_covariance: np.ndarray,
        simple_symbols: list[str],
    ) -> None:
        result = compute_cluster_report(
            simple_returns, simple_weights, simple_covariance, simple_symbols
        )
        assert set(result.cluster_assignments.keys()) == set(simple_symbols)

    def test_n_clusters_capped_at_n_assets(self) -> None:
        """If n < k, effective clusters should be n."""
        rng = np.random.default_rng(42)
        n = 3
        returns = rng.standard_normal((300, n)) * 0.01
        weights = np.array([0.4, 0.3, 0.3])
        cov = np.cov(returns, rowvar=False)
        symbols = ["A", "B", "C"]
        result = compute_cluster_report(returns, weights, cov, symbols, k=10)
        # Can't have more clusters than assets
        assert result.n_clusters <= n

    def test_single_asset_trivial(self) -> None:
        returns = np.array([[0.01], [0.02], [-0.01]])
        weights = np.array([1.0])
        cov = np.array([[0.0001]])
        symbols = ["ONLY"]
        result = compute_cluster_report(returns, weights, cov, symbols)
        assert result.n_clusters == 1
        assert result.effective_n_bets == Decimal("1.0")
        assert "ONLY" in result.cluster_assignments

    def test_max_cluster_weight_is_decimal(
        self,
        simple_returns: np.ndarray,
        simple_weights: np.ndarray,
        simple_covariance: np.ndarray,
        simple_symbols: list[str],
    ) -> None:
        result = compute_cluster_report(
            simple_returns, simple_weights, simple_covariance, simple_symbols
        )
        assert isinstance(result.max_cluster_weight, Decimal)
        assert isinstance(result.herfindahl_index, Decimal)
        assert isinstance(result.effective_n_bets, Decimal)

    def test_enb_greater_than_one_for_diversified_portfolio(self) -> None:
        """ENB > 1 when portfolio has > 1 asset with non-zero weight."""
        rng = np.random.default_rng(42)
        n = 10
        returns = rng.standard_normal((300, n)) * 0.01
        weights = np.ones(n) / n
        cov = np.cov(returns, rowvar=False)
        symbols = [f"S{i}" for i in range(n)]
        result = compute_cluster_report(returns, weights, cov, symbols)
        assert float(result.effective_n_bets) > 1.0

    def test_warning_on_insufficient_overlap(self) -> None:
        """Should emit a warning when pairs have < 60 overlapping days."""
        returns = np.full((300, 3), np.nan)
        rng = np.random.default_rng(42)
        # Asset 0: only first 50 rows
        returns[0:50, 0] = rng.standard_normal(50) * 0.01
        # Asset 1: only last 50 rows (no overlap with asset 0)
        returns[250:300, 1] = rng.standard_normal(50) * 0.01
        # Asset 2: full data
        returns[:, 2] = rng.standard_normal(300) * 0.01

        weights = np.array([0.3, 0.3, 0.4])
        cov = np.eye(3) * 0.01
        symbols = ["A", "B", "C"]

        with pytest.warns(UserWarning, match="Excluded.*asset pair"):
            compute_cluster_report(returns, weights, cov, symbols)

    def test_herfindahl_between_zero_and_one(
        self,
        simple_returns: np.ndarray,
        simple_weights: np.ndarray,
        simple_covariance: np.ndarray,
        simple_symbols: list[str],
    ) -> None:
        result = compute_cluster_report(
            simple_returns, simple_weights, simple_covariance, simple_symbols
        )
        hhi = float(result.herfindahl_index)
        assert 0.0 <= hhi <= 1.0

    def test_max_cluster_weight_non_negative(
        self,
        simple_returns: np.ndarray,
        simple_weights: np.ndarray,
        simple_covariance: np.ndarray,
        simple_symbols: list[str],
    ) -> None:
        result = compute_cluster_report(
            simple_returns, simple_weights, simple_covariance, simple_symbols
        )
        assert float(result.max_cluster_weight) >= 0.0
