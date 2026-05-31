import { Pane } from '@/components/panels/three-pane';

export default function FeaturesPage() {
  return (
    <div className="h-full flex flex-col gap-3">
      <div>
        <h1 className="text-base font-semibold">Feature Catalog</h1>
        <p className="text-xs text-[var(--color-text-muted)] mt-1">
          Browse computed features, check freshness, and launch notebooks.
        </p>
      </div>
      <Pane title="Features">
        <div className="text-center py-12 text-sm text-[var(--color-text-muted)]">
          Feature catalog — connects to Phase 2 feature store API.
          <br />
          Search, filter by category, view computation lineage.
        </div>
      </Pane>
    </div>
  );
}
