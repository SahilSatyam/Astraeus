import { Pane } from '@/components/panels/three-pane';

export default function HoldingsPage() {
  return (
    <div className="h-full flex flex-col gap-3">
      <div>
        <h1 className="text-base font-semibold">Holdings</h1>
        <p className="text-xs text-[var(--color-text-muted)] mt-1">
          Current portfolio holdings with real-time valuation.
        </p>
      </div>
      <Pane title="Portfolio Holdings">
        <div className="text-center py-12 text-sm text-[var(--color-text-muted)]">
          Portfolio dashboard — connects to Phase 4 portfolio service.
          <br />
          Holdings grid, sector breakdown, concentration metrics.
        </div>
      </Pane>
    </div>
  );
}
