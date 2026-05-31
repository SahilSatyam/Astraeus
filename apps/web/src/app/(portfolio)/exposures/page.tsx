import { Pane } from '@/components/panels/three-pane';

export default function ExposuresPage() {
  return (
    <div className="h-full flex flex-col gap-3">
      <div>
        <h1 className="text-base font-semibold">Exposures</h1>
        <p className="text-xs text-[var(--color-text-muted)] mt-1">
          Factor, sector, and geographic exposure breakdown.
        </p>
      </div>
      <Pane title="Exposure Analysis">
        <div className="text-center py-12 text-sm text-[var(--color-text-muted)]">
          Exposure dashboard — connects to Phase 4 risk engine.
          <br />
          Factor heatmap, sector treemap, geographic breakdown.
        </div>
      </Pane>
    </div>
  );
}
