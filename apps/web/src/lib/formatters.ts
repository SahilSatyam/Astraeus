/**
 * Finance-specific formatters.
 *
 * Tabular numerals, thousands separators, bps/percentage tokens,
 * delta coloring helpers.
 */

/** Format a number with thousands separators and fixed decimals. */
export function formatNumber(value: number, decimals = 2): string {
  return value.toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

/** Format as percentage (0.0534 → "5.34%"). */
export function formatPercent(value: number, decimals = 2): string {
  return `${(value * 100).toFixed(decimals)}%`;
}

/** Format as basis points (0.0001 → "1.0 bps"). */
export function formatBps(value: number, decimals = 1): string {
  return `${(value * 10000).toFixed(decimals)} bps`;
}

/** Format USD currency. */
export function formatUsd(value: number, decimals = 2): string {
  const prefix = value < 0 ? '-$' : '$';
  return `${prefix}${formatNumber(Math.abs(value), decimals)}`;
}

/** Format a delta with +/- prefix. */
export function formatDelta(value: number, decimals = 2): string {
  const prefix = value > 0 ? '+' : '';
  return `${prefix}${formatNumber(value, decimals)}`;
}

/** Format a delta as percentage with +/- prefix. */
export function formatDeltaPercent(value: number, decimals = 2): string {
  const prefix = value > 0 ? '+' : '';
  return `${prefix}${(value * 100).toFixed(decimals)}%`;
}

/** Get CSS class for positive/negative/neutral delta. */
export function deltaColor(value: number): string {
  if (value > 0) return 'text-positive';
  if (value < 0) return 'text-negative';
  return 'text-muted';
}

/** Format a timestamp to locale time string. */
export function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
}

/** Format a date to YYYY-MM-DD. */
export function formatDate(iso: string): string {
  return new Date(iso).toISOString().slice(0, 10);
}

/** Format duration in ms to human-readable. */
export function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  return `${(ms / 60_000).toFixed(1)}m`;
}

/** Truncate a string with ellipsis. */
export function truncate(str: string, maxLen: number): string {
  if (str.length <= maxLen) return str;
  return str.slice(0, maxLen - 1) + '…';
}
