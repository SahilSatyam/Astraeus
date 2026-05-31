import { formatDelta, formatDeltaPercent, deltaColor } from '@/lib/formatters';

interface DeltaProps {
  value: number;
  format?: 'number' | 'percent';
  decimals?: number;
  className?: string;
}

/**
 * Color-coded delta display.
 * Green for positive, red for negative, muted for zero.
 */
export function Delta({ value, format = 'number', decimals = 2, className = '' }: DeltaProps) {
  const formatted = format === 'percent' ? formatDeltaPercent(value, decimals) : formatDelta(value, decimals);
  const color = deltaColor(value);

  return (
    <span className={`font-mono tabular-nums ${color} ${className}`}>
      {formatted}
    </span>
  );
}
