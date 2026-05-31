'use client';

import { useQuery } from '@tanstack/react-query';
import { recon, type ReconDrift } from '@/lib/api-client';
import { Pane } from '@/components/panels/three-pane';
import { StatusIndicator } from '@/components/semantic/status-indicator';
import { formatTime } from '@/lib/formatters';

export default function ReconPage() {
  const { data: drifts, isLoading } = useQuery({
    queryKey: ['recon', 'drift'],
    queryFn: () => recon.getDrift(),
    refetchInterval: 5000, // Match recon worker cadence
  });

  const openDrifts = drifts?.filter((d) => !d.resolved_at) ?? [];
  const resolvedDrifts = drifts?.filter((d) => d.resolved_at) ?? [];

  return (
    <div className="h-full flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <h1 className="text-base font-semibold">Reconciliation</h1>
        <div className="flex items-center gap-2">
          {openDrifts.length > 0 ? (
            <span className="text-xs font-medium text-[var(--color-status-error)]">
              ⚠ {openDrifts.length} open drift{openDrifts.length > 1 ? 's' : ''}
            </span>
          ) : (
            <span className="text-xs text-[var(--color-positive)]">✓ No drift</span>
          )}
        </div>
      </div>

      <Pane title="Open Drifts">
        {isLoading ? (
          <div className="text-sm text-[var(--color-text-muted)]">Loading...</div>
        ) : openDrifts.length === 0 ? (
          <div className="text-center py-8 text-sm text-[var(--color-text-muted)]">
            All clear — no reconciliation drift detected
          </div>
        ) : (
          <DriftTable drifts={openDrifts} />
        )}
      </Pane>

      {resolvedDrifts.length > 0 && (
        <Pane title="Recently Resolved">
          <DriftTable drifts={resolvedDrifts.slice(0, 20)} />
        </Pane>
      )}
    </div>
  );
}

function DriftTable({ drifts }: { drifts: ReconDrift[] }) {
  return (
    <div className="overflow-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-[var(--color-border-muted)] text-[var(--color-text-muted)]">
            <th className="text-left py-1.5 px-2">Kind</th>
            <th className="text-left py-1.5 px-2">Account</th>
            <th className="text-left py-1.5 px-2">Local</th>
            <th className="text-left py-1.5 px-2">Broker</th>
            <th className="text-left py-1.5 px-2">Detected</th>
            <th className="text-left py-1.5 px-2">Status</th>
          </tr>
        </thead>
        <tbody>
          {drifts.map((drift) => (
            <tr
              key={drift.diff_id}
              className="border-b border-[var(--color-border-muted)] hover:bg-[var(--color-bg-elevated)]"
            >
              <td className="py-1.5 px-2 font-medium">{drift.kind}</td>
              <td className="py-1.5 px-2">{drift.account_id}</td>
              <td className="py-1.5 px-2 font-mono text-[11px] text-[var(--color-text-secondary)]">
                {drift.local_repr ? JSON.stringify(drift.local_repr).slice(0, 40) : '—'}
              </td>
              <td className="py-1.5 px-2 font-mono text-[11px] text-[var(--color-text-secondary)]">
                {drift.broker_repr ? JSON.stringify(drift.broker_repr).slice(0, 40) : '—'}
              </td>
              <td className="py-1.5 px-2 text-[var(--color-text-muted)]">
                {formatTime(drift.detected_at)}
              </td>
              <td className="py-1.5 px-2">
                <StatusIndicator status={drift.resolved_at ? 'completed' : 'pending'} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
