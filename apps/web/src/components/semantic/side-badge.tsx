interface SideBadgeProps {
  side: 'long' | 'short' | 'flat' | 'buy' | 'sell';
  className?: string;
}

const SIDE_STYLES: Record<string, string> = {
  long: 'bg-[var(--color-side-long)]/15 text-[var(--color-side-long)] border-[var(--color-side-long)]/30',
  buy: 'bg-[var(--color-side-long)]/15 text-[var(--color-side-long)] border-[var(--color-side-long)]/30',
  short: 'bg-[var(--color-side-short)]/15 text-[var(--color-side-short)] border-[var(--color-side-short)]/30',
  sell: 'bg-[var(--color-side-short)]/15 text-[var(--color-side-short)] border-[var(--color-side-short)]/30',
  flat: 'bg-[var(--color-side-flat)]/15 text-[var(--color-side-flat)] border-[var(--color-side-flat)]/30',
};

/**
 * Trade side badge (long/short/flat or buy/sell).
 */
export function SideBadge({ side, className = '' }: SideBadgeProps) {
  const style = SIDE_STYLES[side] || SIDE_STYLES.flat;

  return (
    <span
      className={`inline-block px-2 py-0.5 rounded text-xs font-semibold uppercase border ${style} ${className}`}
    >
      {side}
    </span>
  );
}
