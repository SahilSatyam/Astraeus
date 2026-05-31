'use client';

import { Pane } from '@/components/panels/three-pane';
import { useWsChannel } from '@/hooks/use-ws-channel';
import { useAppStore } from '@/lib/store';
import { Delta } from '@/components/semantic/delta';
import { formatUsd, formatTime } from '@/lib/formatters';
import { z } from 'zod';

const pnlSchema = z.object({
  timestamp: z.string(),
  realized_pnl: z.number(),
  unrealized_pnl: z.number(),
  total_pnl: z.number(),
  daily_pnl: z.number(),
});

export default function PnlPage() {
  const { activeAccount } = useAppStore();

  const pnlUpdates = useWsChannel(`pnl.${activeAccount}`, pnlSchema, 200);
  const latest = pnlUpdates[pnlUpdates.length - 1];

  return (
    <div className="h-full flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <h1 className="text-base font-semibold">PnL</h1>
        <span className="text-xs text-[var(--color-text-muted)]">
          Live — {activeAccount}
        </span>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-4 gap-3">
        <PnlCard label="Daily PnL" value={latest?.daily_pnl ?? 0} />
        <PnlCard label="Unrealized" value={latest?.unrealized_pnl ?? 0} />
        <PnlCard label="Realized" value={latest?.realized_pnl ?? 0} />
        <PnlCard label="Total" value={latest?.total_pnl ?? 0} />
      </div>

      <Pane title="PnL Stream">
        {pnlUpdates.length === 0 ? (
          <div className="text-center py-8 text-sm text-[var(--color-text-muted)]">
            Waiting for PnL updates via WebSocket...
          </div>
        ) : (
          <div className="overflow-auto max-h-96">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-[var(--color-border-muted)] text-[var(--color-text-muted)]">
                  <th className="text-left py-1.5 px-2">Time</th>
                  <th className="text-right py-1.5 px-2">Daily</th>
                  <th className="text-right py-1.5 px-2">Unrealized</th>
                  <th className="text-right py-1.5 px-2">Realized</th>
                  <th className="text-right py-1.5 px-2">Total</th>
                </tr>
              </thead>
              <tbody>
                {[...pnlUpdates].reverse().slice(0, 50).map((update, i) => (
                  <tr key={i} className="border-b border-[var(--color-border-muted)]">
                    <td className="py-1 px-2 font-mono text-[var(--color-text-muted)]">
                      {formatTime(update.timestamp)}
                    </td>
                    <td className="py-1 px-2 text-right"><Delta value={update.daily_pnl} /></td>
                    <td className="py-1 px-2 text-right"><Delta value={update.unrealized_pnl} /></td>
                    <td className="py-1 px-2 text-right"><Delta value={update.realized_pnl} /></td>
                    <td className="py-1 px-2 text-right"><Delta value={update.total_pnl} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Pane>
    </div>
  );
}

function PnlCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="p-3 rounded border border-[var(--color-border)] bg-[var(--color-bg-surface)]">
      <div className="text-[11px] text-[var(--color-text-muted)] mb-1">{label}</div>
      <div className="text-lg font-mono tabular-nums">
        <Delta value={value} />
      </div>
    </div>
  );
}
