import { Pane } from '@/components/panels/three-pane';

export default function NewsPage() {
  return (
    <div className="h-full flex flex-col gap-3">
      <div>
        <h1 className="text-base font-semibold">News & Sentiment</h1>
        <p className="text-xs text-[var(--color-text-muted)] mt-1">
          Research terminal — news feed, sentiment scores, topic clustering.
        </p>
      </div>
      <Pane title="Research Terminal">
        <div className="text-center py-12 text-sm text-[var(--color-text-muted)]">
          News & sentiment terminal — connects to Phase 5 alt-data APIs.
          <br />
          Ticker drilldown, sentiment heatmap, event studies.
        </div>
      </Pane>
    </div>
  );
}
