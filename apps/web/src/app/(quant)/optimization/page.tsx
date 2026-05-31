import { Pane } from '@/components/panels/three-pane';

export default function OptimizationPage() {
  return (
    <div className="h-full flex flex-col gap-3">
      <div>
        <h1 className="text-base font-semibold">Optimization</h1>
        <p className="text-xs text-[var(--color-text-muted)] mt-1">
          Portfolio optimization runs and efficient frontier visualization.
        </p>
      </div>
      <Pane title="Optimizer">
        <div className="text-center py-12 text-sm text-[var(--color-text-muted)]">
          Optimization dashboard — connects to Phase 4 portfolio optimizer.
          <br />
          Efficient frontier, constraint visualization, rebalance suggestions.
        </div>
      </Pane>
    </div>
  );
}
