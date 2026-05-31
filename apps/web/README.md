# Astraeus Web — Operator Terminal

Phase 9 frontend: an institutional-grade operator terminal built with Next.js (App Router), TypeScript, and Tailwind CSS.

## Architecture

- **Framework:** Next.js 16 with App Router, React Server Components where applicable
- **Styling:** Tailwind CSS + semantic finance color tokens (`src/styles/tokens.css`)
- **State:** Zustand (cross-tree), TanStack Query (server state), URL state (filters)
- **Real-time:** WebSocket for hot data (PnL, positions), SSE for log-style streams (agent steps)
- **Charts:** ECharts (general), Lightweight Charts (price-only views)
- **Tables:** TanStack Table + react-virtual for virtualized grids
- **Auth:** NextAuth (single-user JWT for scope mode)

## Module Map

| Route Group | Backend Phase | Description |
|---|---|---|
| `(research)/data-health` | Phase 1 | Ingestion runs, data gaps, lineage |
| `(research)/features` | Phase 2 | Feature catalog, freshness |
| `(research)/news` | Phase 5 | News feed, sentiment, topics |
| `(research)/copilot` | Phase 6 | AI agent workflows, thesis viewer |
| `(quant)/backtests` | Phase 3 | Backtest results, equity curves |
| `(quant)/optimization` | Phase 4 | Portfolio optimizer |
| `(portfolio)/*` | Phase 4 | Holdings, exposures, attribution |
| `(recommendations)/approve` | Phase 7 | Recommendation review + HITL approval |
| `(trading)/*` | Phase 8 | Orders, positions, live PnL |
| `(operator)/*` | Cross-phase | Kill switches, reconciliation |

## Development

```bash
npm install
npm run dev
```

Requires the backend API running at `http://localhost:8000` (configurable via `NEXT_PUBLIC_API_URL`).

## Key Design Decisions

- **Information density over whitespace.** 13px base font, tabular numerals, tight line-height. Bloomberg, not Robinhood.
- **Keyboard-first.** Command palette (`Ctrl+K`), arrow-key grid navigation, shortcut hints.
- **Real-time tiering.** WS for symmetric live updates, SSE for append streams, polling for cold data.
- **OpenAPI codegen contract.** Types generated from backend FastAPI specs (planned).
- **RBAC defensive.** Frontend hides UI; backend is the authority.

## Performance Budget

- TTI < 3s on cold load
- Live grid: 1000 rows at 60fps (virtualized)
- No route bundle > 250 KB gzipped
- Charts dynamic-imported to avoid bundle bloat
