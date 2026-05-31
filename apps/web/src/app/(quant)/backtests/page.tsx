import { Pane } from '@/components/panels/three-pane';

export default function BacktestsPage() {
  return (
    <div className="h-full flex flex-col gap-3">
      <div>
        <h1 className="text-base font-semibold">Backtests</h1>
        <p className="text-xs text-[var(--color-text-muted)] mt-1">
          Strategy backtest results, equity curves, and walk-forward analysis.
        </p>
      </div>
      <Pane title="Backtest Results">
        <div className="text-center py-12 text-sm text-[var(--color-text-muted)]">
          Quant dashboard — connects to Phase 3 backtest registry.
          <br />
          Equity curves (ECharts), metrics tables, walk-forward charts.
        </div>
      </Pane>
    </div>
  );
}
