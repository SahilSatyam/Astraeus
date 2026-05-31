'use client';

import { useQuery } from '@tanstack/react-query';
import { oms, type Position } from '@/lib/api-client';
import { useAppStore } from '@/lib/store';
import { Pane } from '@/components/panels/three-pane';
import { Delta } from '@/components/semantic/delta';
import { formatUsd, formatNumber } from '@/lib/formatters';

export default function PositionsPage() {
  const { activeAccount } = useAppStore();

  const { data: positions, isLoading } = useQuery({
    queryKey: ['positions', activeAccount],
    queryFn: () => oms.getPositions(activeAccount),
    refetchInterval: 5000,
  });

  const totalValue = positions?.reduce(
    (sum, p) => sum + parseFloat(p.market_value || '0'),
    0,
  ) ?? 0;

  const totalPnl = positions?.reduce(
    (sum, p) => sum + parseFloat(p.unrealized_pnl || '0'),
    0,
  ) ?? 0;

  return (
    <div className="h-full flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <h1 className="text-base font-semibold">Positions</h1>
        <div className="flex items-center gap-4 text-xs">
          <span className="text-[var(--color-text-muted)]">
            Market Value: <span className="font-mono tabular-nums text-[var(--color-text-primary)]">{formatUsd(totalValue)}</span>
          </span>
          <span className="text-[var(--color-text-muted)]">
            Unrealized PnL: <Delta value={totalPnl} format="number" />
          </span>
        </div>
      </div>

      <Pane title={`Holdings — ${activeAccount}`}>
        {isLoading ? (
          <div className="text-sm text-[var(--color-text-muted)]">Loading...</div>
        ) : (
          <PositionTable positions={positions ?? []} />
        )}
      </Pane>
    </div>
  );
}

function PositionTable({ positions }: { positions: Position[] }) {
  return (
    <div className="overflow-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-[var(--color-border-muted)] text-[var(--color-text-muted)]">
            <th className="text-left py-1.5 px-2">Symbol</th>
            <th className="text-right py-1.5 px-2">Qty</th>
            <th className="text-right py-1.5 px-2">Avg Cost</th>
            <th className="text-right py-1.5 px-2">Mkt Value</th>
            <th className="text-right py-1.5 px-2">Unrealized PnL</th>
          </tr>
        </thead>
        <tbody>
          {positions.map((pos) => (
            <tr
              key={`${pos.account_id}-${pos.symbol}`}
              className="border-b border-[var(--color-border-muted)] hover:bg-[var(--color-bg-elevated)]"
            >
              <td className="py-1.5 px-2 font-semibold">{pos.symbol}</td>
              <td className="py-1.5 px-2 text-right font-mono tabular-nums">
                {formatNumber(parseFloat(pos.qty), 2)}
              </td>
              <td className="py-1.5 px-2 text-right font-mono tabular-nums">
                {formatUsd(parseFloat(pos.avg_cost))}
              </td>
              <td className="py-1.5 px-2 text-right font-mono tabular-nums">
                {pos.market_value ? formatUsd(parseFloat(pos.market_value)) : '—'}
              </td>
              <td className="py-1.5 px-2 text-right">
                {pos.unrealized_pnl ? (
                  <Delta value={parseFloat(pos.unrealized_pnl)} />
                ) : (
                  '—'
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {positions.length === 0 && (
        <div className="text-center py-8 text-sm text-[var(--color-text-muted)]">
          No positions
        </div>
      )}
    </div>
  );
}
