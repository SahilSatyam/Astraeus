# Phase 9 — Frontend

**Timeline:** Weeks 8–32 (parallel with backend) · **Depends on:** all backend phases for content · **Blocks:** none

---

## 1. Phase Goals & Refined Exit Criteria

The frontend is an **operator's terminal**, not a consumer fintech app. The reference points are Bloomberg, Eikon, and Two Sigma's internal dashboards — dense information, keyboard-first, decisions per square inch. Consumer-fintech polish (Robinhood, Public) is the *wrong target*. A trader does not want pastel gradients and gentle motion; they want monospaced numbers, color-coded deltas, and three panes visible at once.

Refined exit criteria:

- **Module rollout aligned to backend phases.** Each backend phase ships with a corresponding visible UI surface, demonstrable to a stakeholder.
- **Information density**: every key dashboard fits 3+ analytical panes above the fold on a 1920×1080 display without scroll.
- **Keyboard-first navigation**: all primary workflows reachable via keyboard; command palette (`⌘K`) covers 90% of routine actions.
- **Real-time updates** with controlled fan-out: WebSocket for streaming numerics, SSE for log-style append, TanStack Query for cached snapshots. No naive polling on hot data.
- **RBAC awareness**: components render based on role; backend RBAC is the authority, frontend is defensive only.
- **Performance budget**: TTI < 3s on cold load; live grid renders 1000 rows at 60fps via virtualization.

---

## 2. Scope Boundaries

| In | Out |
|---|---|
| Next.js (App Router) + TypeScript + Tailwind | Multi-language i18n |
| ECharts as primary chart library | D3 from-scratch viz |
| Server components for heavy tables | Server-rendered everything |
| WebSocket for live PnL/positions | Push notifications, mobile app |
| AI Copilot (Phase 6 hookups) | Voice control |
| NextAuth with JWT to backend | OAuth-as-IdP for third parties |
| Storybook for component library | Pixel-perfect design system reset |
| Playwright for E2E | Cross-browser at IE/legacy levels |

---

## 3. Module Rollout Aligned to Backend Phases

| Week | Backend ready | Frontend module |
|---|---|---|
| 8–10 | Phase 1 (data) | Data Health & Lineage Browser |
| 10–12 | Phase 2 (features) | Feature Catalog + Notebook launcher |
| 12–14 | Phase 3 (backtests) | Quant Dashboard: backtest results, walk-forward chart |
| 16–18 | Phase 4 (portfolio) | Portfolio Dashboard: holdings, exposures, attribution |
| 18–20 | Phase 5 (alt-data) | Research Terminal: news/sentiment/topics, ticker drilldown |
| 22–24 | Phase 6 (agents) | AI Copilot panel + thesis viewer |
| 26–28 | Phase 7 (recommender) | Recommendation review + approval UI |
| 28–30 | Phase 8 (trading) | Trading Dashboard: orders, fills, positions live |
| 30–32 | cross-phase | Operator Console: kill-switch, recon health, agent observability |

---

## 4. Component & Architecture

```
apps/web/
├─ app/                           # App Router
│  ├─ (research)/
│  │  ├─ data-health/
│  │  ├─ features/
│  │  ├─ news/
│  │  └─ copilot/
│  ├─ (quant)/
│  │  ├─ backtests/
│  │  └─ optimization/
│  ├─ (portfolio)/
│  │  ├─ holdings/
│  │  ├─ exposures/
│  │  └─ attribution/
│  ├─ (recommendations)/
│  │  └─ approve/
│  ├─ (trading)/
│  │  ├─ orders/
│  │  ├─ positions/
│  │  └─ pnl/
│  ├─ (operator)/
│  │  ├─ kill-switch/
│  │  └─ recon/
│  ├─ api/                        # BFF route handlers
│  ├─ layout.tsx                  # global shell
│  └─ command-palette.tsx
├─ components/
│  ├─ charts/                     # ECharts wrappers
│  ├─ tables/                     # virtualized grid
│  ├─ panels/                     # multi-pane layout primitives
│  ├─ semantic/                   # delta, regime-pill, side-badge
│  └─ ui/                         # shadcn/ui base
├─ hooks/
│  ├─ use-ws-channel.ts
│  ├─ use-sse-stream.ts
│  └─ use-rbac.ts
├─ lib/
│  ├─ api-client.ts               # OpenAPI codegen output
│  ├─ ws-manager.ts
│  └─ formatters.ts
└─ styles/
   └─ tokens.css                  # finance color tokens
```

**Server vs client components.** Heavy aggregations (portfolio attribution table, backtest result list) ship as server components — fewer KB to the wire and the formatting is server-side. Interactive panes (live PnL, command palette, charts that respond to scrubbing) are client components. Streaming via React Server Components Suspense for slow stages (e.g., AI Copilot waiting on Phase 6).

```tsx
// app/(quant)/backtests/[runId]/page.tsx — server component
export default async function BacktestPage({ params }) {
  const meta = await api.backtest.get(params.runId);
  return (
    <ThreePane>
      <Pane title="Equity curve">
        <Suspense fallback={<ChartSkeleton/>}>
          <EquityChartSC runId={params.runId}/>{/* server */}
        </Suspense>
      </Pane>
      <Pane title="Metrics"><MetricsTableSC runId={params.runId}/></Pane>
      <Pane title="Run config"><RunConfigSC meta={meta}/></Pane>
    </ThreePane>
  );
}
```

---

## 5. Folder & File Structure

(See section 4.)

Naming convention: route groups in parentheses match backend domain boundaries; co-located `_components` directories for route-private pieces. Public components live in `apps/web/components/` and follow shadcn-style — copy-pastable, owned not consumed.

---

## 6. Data Layer

| Data type | Mechanism | Cache key strategy |
|---|---|---|
| Static metadata (strategy list, model registry) | TanStack Query, `staleTime: 60s` | `[domain, kind, params]` |
| Backtest results, attribution | Server components + revalidate(60) | server-side cache |
| Live PnL, positions | WebSocket via `use-ws-channel` | normalized in-memory store |
| Order events | SSE stream append | append-only event ring |
| Feature search | TanStack Query infinite | `[features, q, filters, page]` |
| Agent run progress | SSE per-run stream | per-run-id local store |

```ts
// hooks/use-ws-channel.ts
export function useWsChannel<T>(channel: string, schema: ZodSchema<T>) {
  const [state, setState] = useState<T[]>([]);
  useEffect(() => {
    const sub = wsManager.subscribe(channel, msg => {
      const parsed = schema.safeParse(msg);
      if (parsed.success) setState(prev => updateRing(prev, parsed.data));
    });
    return () => sub.unsubscribe();
  }, [channel]);
  return state;
}
```

WS reconnection uses exponential backoff with jitter; on reconnect we re-fetch a snapshot via REST and resume the stream — a stale stream that silently disconnected is the worst failure mode for trading UIs.

---

## 7. API Surface Consumed

OpenAPI spec served from each backend FastAPI app; codegen via `openapi-typescript` produces typed clients in `apps/web/lib/api-client.ts`. One source of truth for types; manual `any` in API calls is a CI-failable lint.

Per-module endpoints (representative):

- Data Health: `GET /md/runs`, `GET /md/lineage`, `GET /md/gaps`.
- Backtests: `GET /research/backtest/{id}`, `GET /research/backtest/{id}/result`.
- Portfolio: `GET /portfolio/holdings`, `GET /portfolio/attribution`.
- Recommendations: `GET /reco/recommendations`, `POST /reco/recommendations/{id}/decide`.
- Trading: `GET /oms/orders`, `GET /position/{accountId}`, WS `oms.events.<account>`, WS `pnl.<account>`.
- Agents: `POST /agents/workflow`, SSE `/agents/run/{id}/stream`.
- Operator: `POST /killswitch/{scope}/arm`, `GET /recon/drift`.

---

## 8. External Dependencies

| Library | Choice | Rationale |
|---|---|---|
| Framework | Next.js (App Router) | RSC + streaming; App Router is the future; Pages router is a downgrade |
| Lang | TypeScript strict | non-negotiable |
| Styling | Tailwind + tokens | dense UI is faster with utility classes; tokens enforce finance semantics |
| UI primitives | shadcn/ui | own-it model; not a runtime dependency |
| Charts | ECharts (default), Lightweight-Charts (price-only views) | see Section 9 |
| Tables | TanStack Table + react-virtual | virtualization mandatory for grids |
| Data fetching | TanStack Query | cache + retries + invalidation |
| Client state | Zustand for cross-tree state, URL state for filters | Jotai considered; Zustand simpler for our shape |
| Forms | react-hook-form + zod | typed validation co-located |
| Auth | NextAuth + JWT to backend | backend is RBAC authority |
| WebSocket | native + a small manager | no socket.io (overkill, custom protocol baggage) |
| Tests | Playwright (E2E), Vitest (unit), Storybook (visual) | |
| Observability | Sentry, OTel browser SDK | route-level perf + error |

---

## 9. Key Technical Decisions & Tradeoffs

**App Router over Pages Router.** RSC streaming for slow-stage data (Phase 6 agents take seconds), built-in route groups for the multi-domain structure, smaller client bundles for read-heavy pages.

**ECharts vs Recharts vs Lightweight-Charts.** ECharts. Recharts is fine for product dashboards but stutters at thousands of points and lacks the chart types finance needs (candle, volume profile, heatmap, parallel coordinates). Lightweight-Charts is a TradingView library that wins on price-time charts specifically — use it where the chart is *only* candles + indicators (live trading view). ECharts is the workhorse for everything else (attribution, factor exposure, regime overlay, sentiment heatmap).

**Virtualization is mandatory.** A 1000-row positions grid without virtualization tanks any browser. `react-virtual` over `react-window` for hooks ergonomics.

**Real-time strategy: WS for hot, SSE for log-style, polling for cold.** WS is the right primitive for symmetric live updates (positions, PnL). SSE is simpler and proxy-friendly for append-style streams (agent step logs). Polling stays for cold data (yesterday's recommendations) — TanStack Query handles it transparently.

**Type sharing: OpenAPI codegen, not tRPC.** tRPC is great in a single-process Node monorepo; our backend is Python FastAPI. OpenAPI codegen is the contract. tRPC-style type-safety is approximated by zod runtime validators on every WS message.

**State management.** Zustand for cross-tree shared state (active account, selected ticker, kill-switch status). Server state in TanStack Query. URL state for filters and selections. No Redux.

**Color semantics.** Finance UIs have strong conventions: green/red for positive/negative *deltas*, but neutral monospace for *absolute* numbers. Regime pills get distinct hues (risk-on=blue, risk-off=amber, vol_spike=magenta). Color-blind mode swaps to a Cividis palette without losing meaning. Tokens in `styles/tokens.css`, not Tailwind class arithmetic.

**Information density.** Default font size 13px on dashboard pages, 14px on forms. Tabular numerals (`font-variant-numeric: tabular-nums`) on every number column. Tight line-height. The intent is comfortable for an analyst staring at it for 6 hours, not delightful for a viewer scrolling for 30 seconds.

**Why not consumer-fintech polish.** A trader's morning includes scanning ten thousand data points in twenty minutes. White space and animation are noise. The platform's UX moat is specifically *not* looking like Robinhood.

---

## 10. UX Patterns for Institutional Use

- **Multi-pane terminal layout.** Default 3-pane on most dashboards; user can re-pane via splitter; preference persisted.
- **Command palette `⌘K`.** Symbol jump, action invocation, run query, kill-switch toggle, account switch. Fuzzy-search backed by recent actions.
- **Keyboard navigation.** Arrow keys traverse grids; `Tab` between panes; `?` opens shortcut help; `g h` (Vim-ish) jumps to home.
- **Sticky context.** Selected ticker / account is part of the URL; deep-links share state.
- **Right-click context menus** for grid rows: "show in chart", "open in research", "request thesis".
- **Status bar** at the bottom: connection state, latency to API, kill-switch status, open recon drift count.
- **Sticky header rows** on tables; column reorder; column widths persisted per user.
- **Tabular monospace numbers** with right-alignment; thousands separators; bps/percentage formatting tokens.
- **Accessibility**: keyboard-only operability; ARIA on charts via off-screen tables; high-contrast mode.

---

## 11. Risks, Failure Modes & Mitigations

| Risk | Mitigation |
|---|---|
| Perf collapse on large position grids | Virtualization; column-level memoization; aggregate totals computed server-side |
| WS reconnection storms | Exponential backoff with jitter; per-channel back-pressure; on reconnect re-fetch snapshot |
| Stale cache showing wrong PnL | TanStack Query `staleTime: 0` for live data; WS overrides cache for hot keys |
| RBAC bypass attempt via UI | Backend is the authority; frontend RBAC hides UI but never trusts the user |
| AI Copilot rendering tool calls | Renderer is allow-listed by tool name; unknown tool calls render as "structured tool output" not raw HTML |
| XSS via news content | DOMPurify on any RSS/Reddit content before render |
| User confused by stale chart | Every chart shows "as_of" timestamp and updates monotonically; staleness > threshold renders a "stale" overlay |
| Bundle bloat | Per-route bundles; chart libraries dynamic-imported; Storybook excluded from prod |
| Browser tab background-throttle | WS reconnect on visibility change; user warned on returning if data > N minutes stale |

---

## 12. Testing Strategy

**Playwright E2E.** Per critical workflow: backtest run review, recommendation approval, kill-switch flip, order submission (paper). Cross-page state preserved.

**Storybook + Chromatic visual regression.** Every component snapshot pinned; PR diff blocks unintended visual changes.

**Unit (Vitest).** Pure logic in `lib/` and `hooks/`; zod parsers; formatters.

**RBAC integration test.** Each route accessed by every role fixture; assert correct visibility.

**WS contract tests.** Backend ships fixtures; frontend asserts schemas parse against them.

**Performance budgets in CI.** Lighthouse CI gates TTI/LCP per route.

---

## 13. Observability Hooks

- Sentry for errors + replay.
- OpenTelemetry browser SDK; trace context propagated to backend so a UI click → API call → DB query is one span tree.
- Web vitals (LCP, INP, CLS) reported via PostHog or self-hosted equivalent.
- Per-route render duration; alert if any p99 > 2s.
- WS connection-state metric (connected, reconnecting, failed) per session.

---

## 14. Definition of Done

Per module, the bar is the same:
- [ ] Page renders within performance budget.
- [ ] Backend OpenAPI codegen up-to-date; types compile clean.
- [ ] Storybook stories exist for new components.
- [ ] Playwright E2E for at least one happy path and one failure path.
- [ ] RBAC matrix tested for the route.
- [ ] Mobile is *acceptable* (read-only) — operator workflows assumed desktop.
- [ ] Real-time path proven (WS reconnect on dev simulator).

Phase-wide:
- [ ] All eight modules live behind feature flags.
- [ ] Command palette covers ≥ 90% of routine ops.
- [ ] Bundle budget enforced; no route > 250 KB gzipped.
- [ ] OTel browser → backend span linkage proven on at least one E2E.
- [ ] Accessibility audit passes WCAG AA on primary dashboards.

---

## 15. Interview Talking Points

- **Operator UI vs consumer UI.** Discuss why the *right* answer for a trading platform is information density, not whitespace. Bloomberg vs Robinhood as poles.
- **Real-time at scale.** WS for hot, SSE for log, polling for cold. Reconnect semantics that prevent silent staleness.
- **Server components for analytical reads.** Smaller bundles, server-side cache, fewer KB across the wire. Show the route group structure.
- **OpenAPI codegen contract.** One source of truth between Python FastAPI backend and TS frontend. End-to-end type safety without tRPC lock-in.
- **Virtualization + tabular numerals**: details that separate a usable trader UI from a demo-only one.
- **RBAC defensive on frontend, authoritative on backend.** Hide UI for UX, never trust UI for security.

---

## 16. Open Questions

1. Single SPA shell vs per-domain micro-frontends? Lean single SPA for now; revisit if team scales.
2. Mobile read-only target — do we ship a PWA or accept a desktop-only stance? Defer.
3. Custom theme support — operator preference is real; ship a dark/high-contrast/cividis trio first.
4. Heat-map vs treemap for sector exposure — measure with users.
5. AI Copilot as a docked sidebar (always visible) vs modal (`⌘J` to invoke)? Lean docked but resizable; users flip its weight to the chart.

---

## Scope Mode: 2-Year Resume + Self-Sustaining Trading

**Adjustments**

- **Auth:** simplify to a single-user JWT login. NextAuth is *wired* (RBAC scaffolding stays — it's a resume talking point) but the user table has one row and the role matrix has one role. Don't simulate fake users; just be honest in the README that it's single-tenant by design.
- **Hosting:** the web app runs in `docker-compose` alongside the rest of the stack on the dev machine or the $20–40/mo VPS. No Vercel-paid features. Cloudflare free tier in front for TLS + caching.
- **Observability:** Sentry free tier (5k errors/mo is plenty for one user); browser OTel feeds the same self-hosted Tempo/Loki stack as backend.
- **Storybook + Chromatic:** keep Storybook (resume artifact), drop paid Chromatic — use Storybook's local visual diff or open-source alternatives. Or include Chromatic free tier if it stays under the cap.
- **Module rollout schedule:** stretch from "weeks" to "months" — the 8-module list is realistic for a solo dev across the 2 years, not parallel with backend phases at original pace.
- **Performance budgets, virtualization, command palette, server components, OpenAPI codegen, RBAC defensive patterns:** stay 100%. These are the operator-UI talking points.

**What stays (resume-load-bearing)**

- App Router + RSC, ECharts, virtualization, WS/SSE/polling tiering, OpenAPI codegen, command palette, semantic finance tokens, multi-pane terminal layout, accessibility audit. All of it.

**Budget impact:** $0–5/mo (Cloudflare free, Sentry free, optional domain).
