import { Suspense } from 'react';
import { Pane, ThreePane } from '@/components/panels/three-pane';

/**
 * Backtest detail page — server component.
 * Heavy data (equity curve, metrics) rendered server-side.
 * Charts are client components loaded via Suspense.
 */
export default async function BacktestDetailPage({
  params,
}: {
  params: Promise<{ runId: string }>;
}) {
  const { runId } = await params;

  return (
    <div className="h-full flex flex-col gap-3">
      <div>
        <h1 className="text-base font-semibold">Backtest: {runId.slice(0, 8)}</h1>
        <p className="text-xs text-[var(--color-text-muted)]">
          Strategy backtest results with equity curve and metrics.
        </p>
      </div>

      <ThreePane>
        <Pane title="Equity Curve">
          <Suspense fallback={<ChartSkeleton />}>
            <EquityChartSection runId={runId} />
          </Suspense>
        </Pane>

        <Pane title="Metrics">
          <Suspense fallback={<TableSkeleton />}>
            <MetricsSection runId={runId} />
          </Suspense>
        </Pane>

        <Pane title="Run Configuration">
          <Suspense fallback={<TableSkeleton />}>
            <ConfigSection runId={runId} />
          </Suspense>
        </Pane>
      </ThreePane>
    </div>
  );
}

/** Server component — fetches equity curve data. */
async function EquityChartSection({ runId }: { runId: string }) {
  // In production: const data = await api.backtest.getEquityCurve(runId);
  // For now, render placeholder that the client chart component will fill
  return (
    <div className="h-64 flex items-center justify-center text-xs text-[var(--color-text-muted)]">
      Equity curve for run {runId.slice(0, 8)} — connects to Phase 3 backtest API.
      <br />
      ECharts EquityCurve component renders here with server-fetched data.
    </div>
  );
}

/** Server component — fetches metrics table. */
async function MetricsSection({ runId }: { runId: string }) {
  // Placeholder metrics — in production fetched from backend
  const metrics = [
    { label: 'Total Return', value: '—' },
    { label: 'Sharpe Ratio', value: '—' },
    { label: 'Max Drawdown', value: '—' },
    { label: 'Win Rate', value: '—' },
    { label: 'Profit Factor', value: '—' },
    { label: 'Calmar Ratio', value: '—' },
    { label: 'Sortino Ratio', value: '—' },
    { label: 'Avg Trade Duration', value: '—' },
  ];

  return (
    <table className="w-full text-xs">
      <tbody>
        {metrics.map((m) => (
          <tr key={m.label} className="border-b border-[var(--color-border-muted)]">
            <td className="py-1.5 px-2 text-[var(--color-text-muted)]">{m.label}</td>
            <td className="py-1.5 px-2 text-right font-mono tabular-nums">{m.value}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** Server component — fetches run config. */
async function ConfigSection({ runId }: { runId: string }) {
  return (
    <div className="text-xs text-[var(--color-text-muted)]">
      <p>Run ID: {runId}</p>
      <p className="mt-2">
        Configuration details loaded from Phase 3 strategy registry.
      </p>
    </div>
  );
}

function ChartSkeleton() {
  return (
    <div className="h-64 animate-pulse bg-[var(--color-bg-elevated)] rounded" />
  );
}

function TableSkeleton() {
  return (
    <div className="space-y-2">
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="h-4 animate-pulse bg-[var(--color-bg-elevated)] rounded" />
      ))}
    </div>
  );
}
