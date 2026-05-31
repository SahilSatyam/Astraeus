# ADR-0006 — Next.js + React 19 for Frontend

**Status**: accepted
**Date**: 2026-04-01
**Decider(s)**: Sahil

## Context

Phase 9 requires an operator-grade UI for the trading platform. The frontend
needs: server-side rendering for SEO-irrelevant but fast initial loads, API
route proxying, WebSocket support, and a component ecosystem.

## Decision

Next.js 16 with React 19, TypeScript, and Tailwind CSS 4.

Supporting choices:
- **State management:** Zustand (minimal boilerplate, no provider nesting)
- **Data fetching:** TanStack Query (cache, retry, stale-while-revalidate)
- **Tables:** TanStack Table + TanStack Virtual (10k+ row virtualization)
- **Charts:** ECharts (financial charts, heatmaps) + lightweight-charts (candlesticks)
- **Auth:** NextAuth v4 with JWT strategy (single-user credentials now, OIDC later)
- **Forms:** react-hook-form + Zod (schema-validated forms)
- **Testing:** Vitest (unit), Playwright (e2e), Storybook (component dev)

## Consequences

- Full-stack TypeScript with type-safe API client generation path.
- App Router with route groups maps cleanly to domain modules.
- Standalone output mode enables minimal Docker images.
- React 19 concurrent features improve perceived performance for data-heavy views.
- Tailwind CSS 4 with design tokens provides consistent theming.

## Alternatives considered

- **Remix** — excellent DX but smaller ecosystem for financial charting.
- **SvelteKit** — lighter runtime but team familiarity with React is higher.
- **Plain React SPA** — loses SSR benefits and API route proxying.
