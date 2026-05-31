interface RegimePillProps {
  label: string;
  probability?: number;
  className?: string;
}

const REGIME_COLORS: Record<string, string> = {
  risk_on: 'bg-[var(--color-regime-risk-on)]/20 text-[var(--color-regime-risk-on)] border-[var(--color-regime-risk-on)]/40',
  risk_off: 'bg-[var(--color-regime-risk-off)]/20 text-[var(--color-regime-risk-off)] border-[var(--color-regime-risk-off)]/40',
  vol_spike: 'bg-[var(--color-regime-vol-spike)]/20 text-[var(--color-regime-vol-spike)] border-[var(--color-regime-vol-spike)]/40',
  mean_reversion: 'bg-[var(--color-regime-mean-reversion)]/20 text-[var(--color-regime-mean-reversion)] border-[var(--color-regime-mean-reversion)]/40',
  trending: 'bg-[var(--color-regime-trending)]/20 text-[var(--color-regime-trending)] border-[var(--color-regime-trending)]/40',
  uncertain: 'bg-[var(--color-regime-uncertain)]/20 text-[var(--color-regime-uncertain)] border-[var(--color-regime-uncertain)]/40',
};

/**
 * Regime label pill with semantic coloring.
 */
export function RegimePill({ label, probability, className = '' }: RegimePillProps) {
  const colorClass = REGIME_COLORS[label] || REGIME_COLORS.uncertain;

  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium border ${colorClass} ${className}`}
    >
      <span>{label.replace(/_/g, ' ')}</span>
      {probability !== undefined && (
        <span className="opacity-70">{(probability * 100).toFixed(0)}%</span>
      )}
    </span>
  );
}
