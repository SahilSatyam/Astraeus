/**
 * API client for Astraeus backend services.
 *
 * In production this would be generated from OpenAPI specs via openapi-typescript.
 * For now, typed wrappers around fetch with proper error handling.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export class ApiError extends Error {
  constructor(
    public status: number,
    public statusText: string,
    public body: unknown,
  ) {
    super(`API Error ${status}: ${statusText}`);
    this.name = 'ApiError';
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const url = `${API_BASE}${path}`;
  const res = await fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
  });

  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new ApiError(res.status, res.statusText, body);
  }

  return res.json() as Promise<T>;
}

// --- Market Data / Data Health ---
export const dataHealth = {
  getRuns: (params?: { limit?: number }) =>
    request<DataHealthRun[]>(`/md/runs?limit=${params?.limit ?? 50}`),
  getGaps: () => request<DataGap[]>('/md/gaps'),
  getLineage: (symbol: string) => request<LineageNode[]>(`/md/lineage?symbol=${symbol}`),
};

// --- Recommendations ---
export const reco = {
  getRuns: (date: string) => request<RecoRun[]>(`/reco/runs?date=${date}`),
  getRun: (runId: string) => request<RecoRun>(`/reco/run/${runId}`),
  getRecommendations: (runId: string) =>
    request<Recommendation[]>(`/reco/recommendations?run_id=${runId}`),
  decide: (recId: string, body: DecisionPayload) =>
    request<Recommendation>(`/reco/recommendations/${recId}/decide`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  getRegime: (date: string) => request<RegimeState>(`/reco/regime?date=${date}`),
  replay: (date: string) =>
    request<{ run_id: string }>(`/reco/replay?date=${date}`, { method: 'POST' }),
};

// --- Agents ---
export const agents = {
  startRun: (body: AgentRunRequest) =>
    request<AgentRunResponse>('/agents/runs', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  getRun: (runId: string) => request<AgentRunStatus>(`/agents/runs/${runId}`),
  getTrace: (runId: string) => request<AgentTrace>(`/agents/runs/${runId}/trace`),
};

// --- OMS / Trading ---
export const oms = {
  submitOrder: (body: SubmitOrderRequest) =>
    request<OrderResponse>('/oms/orders', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  cancelOrder: (orderId: string) =>
    request<OrderResponse>(`/oms/orders/${orderId}/cancel`, { method: 'POST' }),
  getOrder: (orderId: string) => request<OrderResponse>(`/oms/orders/${orderId}`),
  getOrders: (params?: { account_id?: string; strategy_id?: string }) => {
    const qs = new URLSearchParams(params as Record<string, string>).toString();
    return request<OrderResponse[]>(`/oms/orders?${qs}`);
  },
  getPositions: (accountId: string) =>
    request<Position[]>(`/position/${accountId}`),
};

// --- Kill Switch ---
export const killSwitch = {
  arm: (scope: string, body: { reason: string }) =>
    request<void>(`/killswitch/${scope}/arm`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  disarm: (scope: string) =>
    request<void>(`/killswitch/${scope}/disarm`, { method: 'POST' }),
};

// --- Reconciliation ---
export const recon = {
  getDrift: (since?: string) =>
    request<ReconDrift[]>(`/recon/drift${since ? `?since=${since}` : ''}`),
};

// --- HITL ---
export const hitl = {
  getPending: () => request<HitlItem[]>('/hitl/items?status=pending'),
  claim: (id: string) => request<HitlItem>(`/hitl/items/${id}/claim`, { method: 'POST' }),
  approve: (id: string) => request<HitlItem>(`/hitl/items/${id}/approve`, { method: 'POST' }),
  reject: (id: string, reason: string) =>
    request<HitlItem>(`/hitl/items/${id}/reject`, {
      method: 'POST',
      body: JSON.stringify({ reason }),
    }),
};

// --- Types ---
export interface DataHealthRun {
  run_id: string;
  source: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  records_ingested: number;
}

export interface DataGap {
  symbol: string;
  gap_start: string;
  gap_end: string;
  source: string;
}

export interface LineageNode {
  id: string;
  type: string;
  upstream: string[];
}

export interface RecoRun {
  run_id: string;
  run_date: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  stage_timings: Record<string, number>;
}

export interface Recommendation {
  rec_id: string;
  run_id: string;
  ticker: string;
  side: 'long' | 'short' | 'flat';
  target_weight: number;
  rank: number;
  composite_score: number;
  component_attribution: Record<string, number>;
  risk_passed: boolean;
  risk_notes: Record<string, unknown> | null;
  thesis_run_id: string | null;
  state: 'proposed' | 'approved' | 'rejected' | 'overridden' | 'expired';
  horizon_days: number;
  created_at: string;
}

export interface DecisionPayload {
  decision: 'approve' | 'reject' | 'override';
  rationale: string;
  override_weight?: number;
}

export interface RegimeState {
  label: string;
  probability: number;
  stability_days: number;
  model: string;
}

export interface AgentRunRequest {
  workflow: string;
  inputs: Record<string, unknown>;
  options?: { channel?: string; max_cost_usd?: number; timeout_s?: number };
}

export interface AgentRunResponse {
  run_id: string;
  status_url: string;
}

export interface AgentRunStatus {
  run_id: string;
  status: 'running' | 'completed' | 'hitl_pending' | 'rejected' | 'failed';
  output: Record<string, unknown> | null;
  trace_url: string;
  cost_usd: number;
  duration_ms: number;
}

export interface AgentTrace {
  steps: AgentStep[];
}

export interface AgentStep {
  step_id: string;
  agent_name: string;
  ordinal: number;
  status: string;
  duration_ms: number;
  cost_usd: number;
}

export interface SubmitOrderRequest {
  client_order_id: string;
  account_id: string;
  strategy_id: string;
  rec_id?: string;
  decision_id?: string;
  symbol: string;
  side: 'buy' | 'sell';
  qty: string;
  order_type: 'market' | 'limit';
  limit_price?: string;
  tif: 'DAY' | 'GTC';
}

export interface OrderResponse {
  order_id: string;
  client_order_id: string;
  symbol: string;
  side: string;
  qty: string;
  state: string;
  broker_order_id: string | null;
  created_at: string;
}

export interface Position {
  account_id: string;
  symbol: string;
  qty: string;
  avg_cost: string;
  market_value?: string;
  unrealized_pnl?: string;
}

export interface ReconDrift {
  diff_id: string;
  account_id: string;
  kind: string;
  local_repr: Record<string, unknown> | null;
  broker_repr: Record<string, unknown> | null;
  detected_at: string;
  resolved_at: string | null;
}

export interface HitlItem {
  id: string;
  run_id: string;
  workflow_key: string;
  triggered_by: string;
  reason: Record<string, unknown>;
  status: string;
  priority: number;
  created_at: string;
}
