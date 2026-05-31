'use client';

import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { agents, type AgentRunStatus } from '@/lib/api-client';
import { useSseStream } from '@/hooks/use-sse-stream';
import { Pane, TwoPane } from '@/components/panels/three-pane';
import { StatusIndicator } from '@/components/semantic/status-indicator';
import { formatDuration, formatUsd } from '@/lib/formatters';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

const WORKFLOWS = [
  { key: 'trade_thesis', label: 'Trade Thesis', description: 'Full research thesis for a ticker' },
  { key: 'daily_brief', label: 'Daily Brief', description: 'Market overview and key events' },
  { key: 'portfolio_commentary', label: 'Portfolio Commentary', description: 'Current portfolio analysis' },
  { key: 'risk_drilldown', label: 'Risk Drill-Down', description: 'Deep risk analysis' },
];

export default function CopilotPage() {
  const [ticker, setTicker] = useState('AAPL');
  const [workflow, setWorkflow] = useState('trade_thesis');
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [runResult, setRunResult] = useState<AgentRunStatus | null>(null);

  // SSE stream for live agent steps
  const sseUrl = activeRunId ? `${API_BASE}/agents/runs/${activeRunId}/stream` : null;
  const { events: steps } = useSseStream<{ agent_name: string; status: string; message: string }>(
    sseUrl,
  );

  const startMutation = useMutation({
    mutationFn: () =>
      agents.startRun({
        workflow,
        inputs: { ticker, as_of: new Date().toISOString(), horizon_days: 30 },
        options: { max_cost_usd: 0.5, timeout_s: 60 },
      }),
    onSuccess: (data) => {
      setActiveRunId(data.run_id);
      setRunResult(null);
      // Poll for completion
      pollRun(data.run_id);
    },
  });

  const pollRun = async (runId: string) => {
    const poll = setInterval(async () => {
      try {
        const status = await agents.getRun(runId);
        if (status.status !== 'running') {
          setRunResult(status);
          clearInterval(poll);
        }
      } catch {
        clearInterval(poll);
      }
    }, 2000);
  };

  return (
    <div className="h-full flex flex-col gap-3">
      <div>
        <h1 className="text-base font-semibold">AI Copilot</h1>
        <p className="text-xs text-[var(--color-text-muted)] mt-1">
          Run agent workflows — trade theses, daily briefs, portfolio commentary.
        </p>
      </div>

      <TwoPane split="vertical" ratio="1fr 2fr">
        {/* Input panel */}
        <Pane title="Run Configuration">
          <div className="space-y-4">
            {/* Workflow selector */}
            <div>
              <label className="text-xs text-[var(--color-text-muted)] block mb-1">Workflow</label>
              <select
                value={workflow}
                onChange={(e) => setWorkflow(e.target.value)}
                className="w-full px-2 py-1.5 text-xs rounded border border-[var(--color-border)] bg-[var(--color-bg)] text-[var(--color-text-primary)]"
              >
                {WORKFLOWS.map((w) => (
                  <option key={w.key} value={w.key}>
                    {w.label}
                  </option>
                ))}
              </select>
              <p className="text-[11px] text-[var(--color-text-muted)] mt-1">
                {WORKFLOWS.find((w) => w.key === workflow)?.description}
              </p>
            </div>

            {/* Ticker input */}
            <div>
              <label className="text-xs text-[var(--color-text-muted)] block mb-1">Ticker</label>
              <input
                type="text"
                value={ticker}
                onChange={(e) => setTicker(e.target.value.toUpperCase())}
                className="w-full px-2 py-1.5 text-xs rounded border border-[var(--color-border)] bg-[var(--color-bg)] text-[var(--color-text-primary)] font-mono"
                placeholder="AAPL"
              />
            </div>

            {/* Run button */}
            <button
              onClick={() => startMutation.mutate()}
              disabled={startMutation.isPending || !ticker}
              className="w-full px-3 py-2 text-xs font-medium rounded bg-[var(--color-status-info)]/20 text-[var(--color-status-info)] border border-[var(--color-status-info)]/30 hover:bg-[var(--color-status-info)]/30 disabled:opacity-50"
            >
              {startMutation.isPending ? 'Starting...' : 'Run Workflow'}
            </button>

            {/* Run metadata */}
            {runResult && (
              <div className="space-y-1 pt-2 border-t border-[var(--color-border-muted)]">
                <div className="flex justify-between text-xs">
                  <span className="text-[var(--color-text-muted)]">Status</span>
                  <StatusIndicator status={runResult.status} />
                </div>
                <div className="flex justify-between text-xs">
                  <span className="text-[var(--color-text-muted)]">Cost</span>
                  <span className="font-mono">{formatUsd(runResult.cost_usd, 4)}</span>
                </div>
                <div className="flex justify-between text-xs">
                  <span className="text-[var(--color-text-muted)]">Duration</span>
                  <span className="font-mono">{formatDuration(runResult.duration_ms)}</span>
                </div>
              </div>
            )}
          </div>
        </Pane>

        {/* Output panel */}
        <Pane title="Agent Output">
          <div className="space-y-3">
            {/* Live step log */}
            {steps.length > 0 && (
              <div className="space-y-1 pb-3 border-b border-[var(--color-border-muted)]">
                <h4 className="text-xs font-medium text-[var(--color-text-muted)]">Steps</h4>
                {steps.map((step, i) => (
                  <div key={i} className="flex items-center gap-2 text-[11px]">
                    <StatusIndicator status={step.status} />
                    <span className="font-medium">{step.agent_name}</span>
                    <span className="text-[var(--color-text-muted)] truncate">{step.message}</span>
                  </div>
                ))}
              </div>
            )}

            {/* Result */}
            {runResult?.output ? (
              <div className="text-xs space-y-2">
                <ThesisOutput output={runResult.output} />
              </div>
            ) : activeRunId && !runResult ? (
              <div className="text-center py-8 text-sm text-[var(--color-text-muted)] animate-pulse">
                Running agent workflow...
              </div>
            ) : (
              <div className="text-center py-8 text-sm text-[var(--color-text-muted)]">
                Configure and run a workflow to see results
              </div>
            )}
          </div>
        </Pane>
      </TwoPane>
    </div>
  );
}

function ThesisOutput({ output }: { output: Record<string, unknown> }) {
  const summary = output.summary as string | undefined;
  const findings = output.supporting_findings as Array<{ claim: string; confidence: string }> | undefined;
  const contradictions = output.contradictory_findings as Array<{ claim: string }> | undefined;

  return (
    <div className="space-y-3">
      {summary && (
        <div>
          <h4 className="text-xs font-medium text-[var(--color-text-muted)] mb-1">Summary</h4>
          <p className="text-xs leading-relaxed">{summary}</p>
        </div>
      )}

      {findings && findings.length > 0 && (
        <div>
          <h4 className="text-xs font-medium text-[var(--color-positive)] mb-1">Supporting</h4>
          <ul className="space-y-1">
            {findings.map((f, i) => (
              <li key={i} className="text-xs flex gap-1">
                <span className="text-[var(--color-positive)]">+</span>
                <span>{f.claim}</span>
                <span className="text-[var(--color-text-muted)]">[{f.confidence}]</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {contradictions && contradictions.length > 0 && (
        <div>
          <h4 className="text-xs font-medium text-[var(--color-negative)] mb-1">Contradictory</h4>
          <ul className="space-y-1">
            {contradictions.map((f, i) => (
              <li key={i} className="text-xs flex gap-1">
                <span className="text-[var(--color-negative)]">−</span>
                <span>{f.claim}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Raw output fallback */}
      {!summary && (
        <pre className="text-[11px] font-mono bg-[var(--color-bg)] p-2 rounded overflow-auto max-h-96">
          {JSON.stringify(output, null, 2)}
        </pre>
      )}
    </div>
  );
}
