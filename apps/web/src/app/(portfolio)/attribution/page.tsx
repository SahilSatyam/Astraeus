import { Pane } from '@/components/panels/three-pane';

export default function AttributionPage() {
  return (
    <div className="h-full flex flex-col gap-3">
      <div>
        <h1 className="text-base font-semibold">Attribution</h1>
        <p className="text-xs text-[var(--color-text-muted)] mt-1">
          Performance attribution by factor, sector, and strategy.
        </p>
      </div>
      <Pane title="Performance Attribution">
        <div className="text-center py-12 text-sm text-[var(--color-text-muted)]">
          Attribution dashboard — connects to Phase 4 portfolio analytics.
          <br />
          Brinson attribution, factor decomposition, strategy contribution.
        </div>
      </Pane>
    </div>
  );
}
