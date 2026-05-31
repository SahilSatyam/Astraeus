'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { reco, type Recommendation, type DecisionPayload } from '@/lib/api-client';
import { Pane, TwoPane } from '@/components/panels/three-pane';
import { SideBadge } from '@/components/semantic/side-badge';
import { StatusIndicator } from '@/components/semantic/status-indicator';
import { RegimePill } from '@/components/semantic/regime-pill';
import { formatNumber, formatPercent, formatDate } from '@/lib/formatters';
import { useState } from 'react';

export default function RecommendationApprovePage() {
  const today = new Date().toISOString().slice(0, 10);
  const [selectedRec, setSelectedRec] = useState<Recommendation | null>(null);

  const { data: runs } = useQuery({
    queryKey: ['reco', 'runs', today],
    queryFn: () => reco.getRuns(today),
  });

  const latestRun = runs?.[0];

  const { data: recommendations, isLoading } = useQuery({
    queryKey: ['reco', 'recommendations', latestRun?.run_id],
    queryFn: () => reco.getRecommendations(latestRun!.run_id),
    enabled: !!latestRun,
  });

  const { data: regime } = useQuery({
    queryKey: ['reco', 'regime', today],
    queryFn: () => reco.getRegime(today),
  });

  return (
    <div className="h-full flex flex-col gap-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-base font-semibold">Recommendations</h1>
          <span className="text-xs text-[var(--color-text-muted)]">{today}</span>
          {regime && <RegimePill label={regime.label} probability={regime.probability} />}
        </div>
        {latestRun && <StatusIndicator status={latestRun.status} />}
      </div>

      {/* Content */}
      <TwoPane split="vertical" ratio="2fr 1fr">
        {/* Recommendation list */}
        <Pane title="Pipeline Output">
          {isLoading ? (
            <div className="text-sm text-[var(--color-text-muted)]">Loading...</div>
          ) : (
            <RecommendationTable
              recommendations={recommendations ?? []}
              selected={selectedRec}
              onSelect={setSelectedRec}
            />
          )}
        </Pane>

        {/* Detail / Decision panel */}
        <Pane title="Decision">
          {selectedRec ? (
            <DecisionPanel recommendation={selectedRec} />
          ) : (
            <div className="text-sm text-[var(--color-text-muted)] text-center py-8">
              Select a recommendation to review
            </div>
          )}
        </Pane>
      </TwoPane>
    </div>
  );
}

function RecommendationTable({
  recommendations,
  selected,
  onSelect,
}: {
  recommendations: Recommendation[];
  selected: Recommendation | null;
  onSelect: (r: Recommendation) => void;
}) {
  return (
    <div className="overflow-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-[var(--color-border-muted)] text-[var(--color-text-muted)]">
            <th className="text-left py-1.5 px-2">#</th>
            <th className="text-left py-1.5 px-2">Ticker</th>
            <th className="text-left py-1.5 px-2">Side</th>
            <th className="text-right py-1.5 px-2">Weight</th>
            <th className="text-right py-1.5 px-2">Score</th>
            <th className="text-center py-1.5 px-2">Risk</th>
            <th className="text-left py-1.5 px-2">State</th>
          </tr>
        </thead>
        <tbody>
          {recommendations.map((rec) => (
            <tr
              key={rec.rec_id}
              onClick={() => onSelect(rec)}
              className={`border-b border-[var(--color-border-muted)] cursor-pointer hover:bg-[var(--color-bg-elevated)] ${
                selected?.rec_id === rec.rec_id ? 'bg-[var(--color-bg-elevated)]' : ''
              }`}
            >
              <td className="py-1.5 px-2 font-mono tabular-nums">{rec.rank}</td>
              <td className="py-1.5 px-2 font-semibold">{rec.ticker}</td>
              <td className="py-1.5 px-2">
                <SideBadge side={rec.side} />
              </td>
              <td className="py-1.5 px-2 text-right font-mono tabular-nums">
                {formatPercent(rec.target_weight)}
              </td>
              <td className="py-1.5 px-2 text-right font-mono tabular-nums">
                {formatNumber(rec.composite_score, 3)}
              </td>
              <td className="py-1.5 px-2 text-center">
                {rec.risk_passed ? (
                  <span className="text-[var(--color-positive)]">✓</span>
                ) : (
                  <span className="text-[var(--color-negative)]">✗</span>
                )}
              </td>
              <td className="py-1.5 px-2">
                <StatusIndicator status={rec.state} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {recommendations.length === 0 && (
        <div className="text-center py-8 text-sm text-[var(--color-text-muted)]">
          No recommendations for today
        </div>
      )}
    </div>
  );
}

function DecisionPanel({ recommendation }: { recommendation: Recommendation }) {
  const queryClient = useQueryClient();
  const [rationale, setRationale] = useState('');
  const [overrideWeight, setOverrideWeight] = useState('');

  const mutation = useMutation({
    mutationFn: (payload: DecisionPayload) => reco.decide(recommendation.rec_id, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['reco', 'recommendations'] });
      setRationale('');
      setOverrideWeight('');
    },
  });

  const handleDecision = (decision: 'approve' | 'reject' | 'override') => {
    const payload: DecisionPayload = {
      decision,
      rationale,
      override_weight: decision === 'override' ? parseFloat(overrideWeight) : undefined,
    };
    mutation.mutate(payload);
  };

  return (
    <div className="space-y-4">
      {/* Summary */}
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <span className="font-semibold text-sm">{recommendation.ticker}</span>
          <SideBadge side={recommendation.side} />
        </div>
        <div className="grid grid-cols-2 gap-2 text-xs">
          <div>
            <span className="text-[var(--color-text-muted)]">Target Weight</span>
            <div className="font-mono tabular-nums">{formatPercent(recommendation.target_weight)}</div>
          </div>
          <div>
            <span className="text-[var(--color-text-muted)]">Composite Score</span>
            <div className="font-mono tabular-nums">{formatNumber(recommendation.composite_score, 4)}</div>
          </div>
          <div>
            <span className="text-[var(--color-text-muted)]">Horizon</span>
            <div>{recommendation.horizon_days} days</div>
          </div>
          <div>
            <span className="text-[var(--color-text-muted)]">Created</span>
            <div>{formatDate(recommendation.created_at)}</div>
          </div>
        </div>
      </div>

      {/* Attribution */}
      <div>
        <h4 className="text-xs font-medium text-[var(--color-text-muted)] mb-1">Signal Attribution</h4>
        <div className="space-y-1">
          {Object.entries(recommendation.component_attribution).map(([signal, value]) => (
            <div key={signal} className="flex items-center justify-between text-xs">
              <span>{signal}</span>
              <span className="font-mono tabular-nums">{formatPercent(value)}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Decision form */}
      {recommendation.state === 'proposed' && (
        <div className="space-y-3 pt-2 border-t border-[var(--color-border-muted)]">
          <div>
            <label className="text-xs text-[var(--color-text-muted)] block mb-1">
              Rationale (required)
            </label>
            <textarea
              value={rationale}
              onChange={(e) => setRationale(e.target.value)}
              className="w-full px-2 py-1.5 text-xs rounded border border-[var(--color-border)] bg-[var(--color-bg)] text-[var(--color-text-primary)] resize-none"
              rows={3}
              placeholder="Why approve/reject/override..."
            />
          </div>

          <div>
            <label className="text-xs text-[var(--color-text-muted)] block mb-1">
              Override Weight (optional)
            </label>
            <input
              type="number"
              step="0.001"
              value={overrideWeight}
              onChange={(e) => setOverrideWeight(e.target.value)}
              className="w-full px-2 py-1.5 text-xs rounded border border-[var(--color-border)] bg-[var(--color-bg)] text-[var(--color-text-primary)] font-mono"
              placeholder="e.g. 0.03"
            />
          </div>

          <div className="flex gap-2">
            <button
              onClick={() => handleDecision('approve')}
              disabled={!rationale || mutation.isPending}
              className="flex-1 px-3 py-1.5 text-xs font-medium rounded bg-[var(--color-positive)]/20 text-[var(--color-positive)] border border-[var(--color-positive)]/30 hover:bg-[var(--color-positive)]/30 disabled:opacity-50"
            >
              Approve
            </button>
            <button
              onClick={() => handleDecision('reject')}
              disabled={!rationale || mutation.isPending}
              className="flex-1 px-3 py-1.5 text-xs font-medium rounded bg-[var(--color-negative)]/20 text-[var(--color-negative)] border border-[var(--color-negative)]/30 hover:bg-[var(--color-negative)]/30 disabled:opacity-50"
            >
              Reject
            </button>
            <button
              onClick={() => handleDecision('override')}
              disabled={!rationale || !overrideWeight || mutation.isPending}
              className="flex-1 px-3 py-1.5 text-xs font-medium rounded bg-[var(--color-status-warning)]/20 text-[var(--color-status-warning)] border border-[var(--color-status-warning)]/30 hover:bg-[var(--color-status-warning)]/30 disabled:opacity-50"
            >
              Override
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
