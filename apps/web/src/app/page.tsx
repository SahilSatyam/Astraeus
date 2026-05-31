import Link from 'next/link';

/**
 * Home page — quick overview with links to key modules.
 */
export default function HomePage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-lg font-semibold text-[var(--color-text-primary)]">
          Astraeus Operator Terminal
        </h1>
        <p className="text-sm text-[var(--color-text-secondary)] mt-1">
          Quantitative trading platform — research, recommendations, execution.
        </p>
      </div>

      <div className="grid grid-cols-3 gap-3">
        <QuickLink
          href="/recommendations/approve"
          title="Recommendations"
          description="Review and approve today's pipeline output"
          accent="var(--color-status-info)"
        />
        <QuickLink
          href="/trading/orders"
          title="Trading"
          description="Live orders, positions, and PnL"
          accent="var(--color-positive)"
        />
        <QuickLink
          href="/operator/kill-switch"
          title="Operator"
          description="Kill switches, reconciliation, system health"
          accent="var(--color-status-warning)"
        />
        <QuickLink
          href="/portfolio/holdings"
          title="Portfolio"
          description="Holdings, exposures, and attribution"
          accent="var(--color-regime-trending)"
        />
        <QuickLink
          href="/research/copilot"
          title="AI Copilot"
          description="Research agent — trade theses, briefs"
          accent="var(--color-regime-vol-spike)"
        />
        <QuickLink
          href="/quant/backtests"
          title="Backtests"
          description="Strategy results and walk-forward analysis"
          accent="var(--color-regime-mean-reversion)"
        />
      </div>

      <div className="text-xs text-[var(--color-text-muted)] mt-8">
        Press <kbd className="px-1 py-0.5 rounded bg-[var(--color-bg-surface)]">⌘K</kbd> to open
        the command palette.
      </div>
    </div>
  );
}

function QuickLink({
  href,
  title,
  description,
  accent,
}: {
  href: string;
  title: string;
  description: string;
  accent: string;
}) {
  return (
    <Link
      href={href}
      className="block p-4 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-surface)] hover:bg-[var(--color-bg-elevated)] transition-colors"
    >
      <div className="flex items-center gap-2 mb-1">
        <span className="w-2 h-2 rounded-full" style={{ backgroundColor: accent }} />
        <h2 className="text-sm font-medium text-[var(--color-text-primary)]">{title}</h2>
      </div>
      <p className="text-xs text-[var(--color-text-secondary)]">{description}</p>
    </Link>
  );
}
