interface StatusIndicatorProps {
  status: string;
  className?: string;
}

const STATUS_COLORS: Record<string, string> = {
  // Pipeline / run statuses
  done: 'bg-[var(--color-status-active)]',
  completed: 'bg-[var(--color-status-active)]',
  running: 'bg-[var(--color-status-info)] animate-pulse',
  queued: 'bg-[var(--color-text-muted)]',
  degraded: 'bg-[var(--color-status-warning)]',
  failed: 'bg-[var(--color-status-error)]',

  // Order states
  filled: 'bg-[var(--color-status-active)]',
  submitted: 'bg-[var(--color-status-info)]',
  partial_fill: 'bg-[var(--color-status-warning)]',
  cancelled: 'bg-[var(--color-text-muted)]',
  rejected: 'bg-[var(--color-status-error)]',
  expired: 'bg-[var(--color-text-muted)]',

  // Recommendation states
  proposed: 'bg-[var(--color-status-info)]',
  approved: 'bg-[var(--color-status-active)]',
  overridden: 'bg-[var(--color-status-warning)]',

  // HITL
  pending: 'bg-[var(--color-status-warning)] animate-pulse',
  claimed: 'bg-[var(--color-status-info)]',

  // Connection
  connected: 'bg-[var(--color-status-active)]',
  disconnected: 'bg-[var(--color-status-error)]',
  reconnecting: 'bg-[var(--color-status-warning)] animate-pulse',
};

/**
 * Small colored dot indicating status.
 */
export function StatusIndicator({ status, className = '' }: StatusIndicatorProps) {
  const color = STATUS_COLORS[status] || 'bg-[var(--color-text-muted)]';

  return (
    <span className={`inline-flex items-center gap-1.5 ${className}`}>
      <span className={`w-2 h-2 rounded-full ${color}`} />
      <span className="text-xs text-[var(--color-text-secondary)]">{status}</span>
    </span>
  );
}
