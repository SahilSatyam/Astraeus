'use client';

import { useQuery } from '@tanstack/react-query';
import { dataHealth, type DataHealthRun, type DataGap } from '@/lib/api-client';
import { Pane, TwoPane } from '@/components/panels/three-pane';
import { StatusIndicator } from '@/components/semantic/status-indicator';
import { formatTime, formatNumber } from '@/lib/formatters';

export default function DataHealthPage() {
  const { data: runs, isLoading: runsLoading } = useQuery({
    queryKey: ['data-health', 'runs'],
    queryFn: () => dataHealth.getRuns({ limit: 20 }),
  });

  const { data: gaps, isLoading: gapsLoading } = useQuery({
    queryKey: ['data-health', 'gaps'],
    queryFn: () => dataHealth.getGaps(),
  });

  return (
    <div className="h-full flex flex-col gap-3">
      <div>
        <h1 className="text-base font-semibold">Data Health</h1>
        <p className="text-xs text-[var(--color-text-muted)] mt-1">
          Ingestion runs, data gaps, and lineage tracking.
        </p>
      </div>

      <TwoPane split="vertical" ratio="1fr 1fr">
        <Pane title="Recent Ingestion Runs">
          {runsLoading ? (
            <div className="text-sm text-[var(--color-text-muted)]">Loading...</div>
          ) : (
            <div className="overflow-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-[var(--color-border-muted)] text-[var(--color-text-muted)]">
                    <th className="text-left py-1.5 px-2">Source</th>
                    <th className="text-left py-1.5 px-2">Status</th>
                    <th className="text-right py-1.5 px-2">Records</th>
                    <th className="text-left py-1.5 px-2">Started</th>
                  </tr>
                </thead>
                <tbody>
                  {(runs ?? []).map((run) => (
                    <tr key={run.run_id} className="border-b border-[var(--color-border-muted)]">
                      <td className="py-1.5 px-2 font-medium">{run.source}</td>
                      <td className="py-1.5 px-2"><StatusIndicator status={run.status} /></td>
                      <td className="py-1.5 px-2 text-right font-mono tabular-nums">
                        {formatNumber(run.records_ingested, 0)}
                      </td>
                      <td className="py-1.5 px-2 text-[var(--color-text-muted)]">
                        {formatTime(run.started_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Pane>

        <Pane title="Data Gaps">
          {gapsLoading ? (
            <div className="text-sm text-[var(--color-text-muted)]">Loading...</div>
          ) : (gaps ?? []).length === 0 ? (
            <div className="text-center py-8 text-sm text-[var(--color-positive)]">
              ✓ No data gaps detected
            </div>
          ) : (
            <div className="overflow-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-[var(--color-border-muted)] text-[var(--color-text-muted)]">
                    <th className="text-left py-1.5 px-2">Symbol</th>
                    <th className="text-left py-1.5 px-2">Source</th>
                    <th className="text-left py-1.5 px-2">Gap Start</th>
                    <th className="text-left py-1.5 px-2">Gap End</th>
                  </tr>
                </thead>
                <tbody>
                  {(gaps ?? []).map((gap, i) => (
                    <tr key={i} className="border-b border-[var(--color-border-muted)]">
                      <td className="py-1.5 px-2 font-semibold">{gap.symbol}</td>
                      <td className="py-1.5 px-2">{gap.source}</td>
                      <td className="py-1.5 px-2 font-mono">{gap.gap_start}</td>
                      <td className="py-1.5 px-2 font-mono">{gap.gap_end}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Pane>
      </TwoPane>
    </div>
  );
}
