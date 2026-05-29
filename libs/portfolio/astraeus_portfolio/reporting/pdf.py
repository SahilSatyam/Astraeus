"""PDF generation via WeasyPrint.

Renders the daily portfolio report as a single PDF per strategy:
- Cover: NAV, daily PnL, status, optimizer used
- Trade list: target weights and changes
- Risk dashboard
- Attribution (from previous day's run)
- Footer: data lineage hashes, code commit, policy version

Generated via Jinja2 → HTML → WeasyPrint → PDF.
"""

from __future__ import annotations

import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import structlog
from jinja2 import Environment, FileSystemLoader

from astraeus_portfolio.contracts import TargetPortfolio
from astraeus_portfolio.reporting.attribution_report import AttributionReportData
from astraeus_portfolio.reporting.exposure import ExposureReport
from astraeus_portfolio.reporting.risk_report import RiskReportData

logger = structlog.get_logger(__name__)

# Template directory
TEMPLATE_DIR = Path(__file__).parent / "templates"


class PDFGenerationError(Exception):
    """Raised when PDF generation fails."""

    pass


class DailyReportRenderer:
    """Renders the daily portfolio report as HTML and optionally PDF.

    The renderer uses Jinja2 templates and WeasyPrint for PDF conversion.
    If WeasyPrint is not available, it falls back to HTML-only output.
    """

    def __init__(self, template_dir: Path | None = None) -> None:
        """Initialize the renderer.

        Args:
            template_dir: Path to the Jinja2 template directory.
                Defaults to the bundled templates/ directory.
        """
        self._template_dir = template_dir or TEMPLATE_DIR
        self._env = Environment(
            loader=FileSystemLoader(str(self._template_dir)),
            autoescape=True,
        )

    def render_html(
        self,
        portfolio: TargetPortfolio,
        exposure: ExposureReport | None = None,
        risk: RiskReportData | None = None,
        attribution: AttributionReportData | None = None,
        policy_version: str = "v1.0",
        code_commit: str | None = None,
    ) -> str:
        """Render the daily report as HTML.

        Args:
            portfolio: The published target portfolio.
            exposure: Exposure report data (optional).
            risk: Risk report data (optional).
            attribution: Attribution report data (optional).
            policy_version: Risk policy version string.
            code_commit: Git commit hash for lineage.

        Returns:
            Rendered HTML string.
        """
        template = self._env.get_template("daily_report.html")

        # Build position data for the template
        positions = []
        prior_weight_map: dict[str, Decimal] = {}
        if exposure and exposure.position_changes:
            prior_weight_map = {
                pc.symbol: pc.prior_weight for pc in exposure.position_changes
            }

        for pw in portfolio.weights:
            prior = prior_weight_map.get(pw.symbol)
            delta = float(pw.weight) - float(prior) if prior is not None else None
            positions.append({
                "symbol": pw.symbol,
                "sector": pw.sector,
                "weight": float(pw.weight),
                "prior_weight": float(prior) if prior is not None else None,
                "delta": delta,
            })

        # Sort by absolute weight descending
        positions.sort(key=lambda p: abs(p["weight"]), reverse=True)

        # Build template context
        context: dict[str, Any] = {
            "strategy_id": portfolio.strategy_id,
            "as_of_date": portfolio.as_of_ts.strftime("%Y-%m-%d"),
            "nav": f"{portfolio.nav:,.2f}",
            "status": portfolio.status.value,
            "optimizer": portfolio.optimizer.value,
            "positions": positions,
            "generated_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
            "policy_version": policy_version,
            "code_commit": code_commit,
            "covariance_estimator": portfolio.covariance_estimator.value,
            "constraint_set_hash": portfolio.constraint_set_hash,
            # Risk data
            "var_table": [],
            "stress_scenarios": [],
            "max_cluster_weight": 0,
            "effective_n_bets": 0,
            "portfolio_beta": 0,
            "liquidity_5day_pct": 0,
            "sector_exposures": [],
            # Attribution
            "attribution": None,
        }

        # Populate risk data if available
        if risk:
            context["var_table"] = [
                {
                    "metric": entry.metric,
                    "confidence": entry.confidence,
                    "historical": float(entry.historical),
                    "parametric": float(entry.parametric) if entry.parametric else None,
                    "monte_carlo": float(entry.monte_carlo) if entry.monte_carlo else None,
                    "discrepancy_flag": entry.discrepancy_flag,
                }
                for entry in risk.var_table
            ]
            context["stress_scenarios"] = [
                {
                    "scenario_name": s.scenario_name,
                    "total_pnl_pct": float(s.total_pnl_pct),
                    "threshold": float(s.threshold),
                    "breached": s.breached,
                }
                for s in risk.stress_scenarios
            ]
            context["max_cluster_weight"] = float(risk.max_cluster_weight)
            context["effective_n_bets"] = float(risk.effective_n_bets)
            context["portfolio_beta"] = float(risk.portfolio_beta)
            context["liquidity_5day_pct"] = float(risk.liquidity_5day_pct)

        # Populate exposure data if available
        if exposure:
            context["sector_exposures"] = [
                {
                    "sector": se.sector,
                    "weight": float(se.weight),
                    "policy_cap": float(se.policy_cap) if se.policy_cap else 0.25,
                }
                for se in exposure.sector_exposures
            ]

        # Populate attribution if available
        if attribution:
            context["attribution"] = {
                "total_pnl_bps": float(attribution.total_pnl_bps),
                "factor_pnl_bps": float(attribution.factor_pnl_bps),
                "idio_pnl_bps": float(attribution.idio_pnl_bps),
                "factor_contributions": [
                    {
                        "factor": fc.factor,
                        "pnl_bps": float(fc.pnl_bps),
                        "pct_of_total": float(fc.pct_of_total) if fc.pct_of_total else None,
                    }
                    for fc in attribution.factor_contributions
                ],
                "top_contributors": [
                    {"symbol": tc.symbol, "pnl_bps": float(tc.pnl_bps), "sector": tc.sector}
                    for tc in attribution.top_contributors
                ],
                "top_detractors": [
                    {"symbol": td.symbol, "pnl_bps": float(td.pnl_bps), "sector": td.sector}
                    for td in attribution.top_detractors
                ],
            }

        html = template.render(**context)
        return html

    def render_pdf(
        self,
        portfolio: TargetPortfolio,
        output_path: str | Path,
        exposure: ExposureReport | None = None,
        risk: RiskReportData | None = None,
        attribution: AttributionReportData | None = None,
        policy_version: str = "v1.0",
        code_commit: str | None = None,
    ) -> Path:
        """Render the daily report as a PDF file.

        Args:
            portfolio: The published target portfolio.
            output_path: File path for the output PDF.
            exposure: Exposure report data (optional).
            risk: Risk report data (optional).
            attribution: Attribution report data (optional).
            policy_version: Risk policy version string.
            code_commit: Git commit hash for lineage.

        Returns:
            Path to the generated PDF file.

        Raises:
            PDFGenerationError: If WeasyPrint is not available or rendering fails.
        """
        html = self.render_html(
            portfolio=portfolio,
            exposure=exposure,
            risk=risk,
            attribution=attribution,
            policy_version=policy_version,
            code_commit=code_commit,
        )

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            from weasyprint import HTML as WeasyHTML

            WeasyHTML(string=html).write_pdf(str(output_path))
            logger.info(
                "pdf_generated",
                strategy_id=portfolio.strategy_id,
                output_path=str(output_path),
                size_bytes=output_path.stat().st_size,
            )
            return output_path

        except ImportError:
            # WeasyPrint not installed — fall back to HTML
            html_path = output_path.with_suffix(".html")
            html_path.write_text(html, encoding="utf-8")
            logger.warning(
                "weasyprint_not_available_html_fallback",
                output_path=str(html_path),
            )
            return html_path

        except Exception as exc:
            raise PDFGenerationError(
                f"Failed to generate PDF: {exc}"
            ) from exc
