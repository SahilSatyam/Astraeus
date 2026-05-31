/**
 * Observability — Sentry error tracking + OpenTelemetry browser SDK.
 *
 * Trace context propagated to backend so a UI click → API call → DB query
 * is one span tree.
 *
 * In scope mode: Sentry free tier (5k errors/mo), OTel feeds self-hosted Tempo.
 */

// --- Sentry ---

let sentryInitialized = false;

export function initSentry() {
  if (sentryInitialized) return;
  if (!process.env.NEXT_PUBLIC_SENTRY_DSN) return;

  // Dynamic import to avoid bundle bloat when Sentry is not configured
  // @ts-expect-error — Sentry is an optional dependency
  import('@sentry/nextjs')
    .then((Sentry: { init: (opts: Record<string, unknown>) => void }) => {
      Sentry.init({
        dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,
        environment: process.env.NODE_ENV,
        tracesSampleRate: 0.1, // 10% of transactions
        replaysSessionSampleRate: 0,
        replaysOnErrorSampleRate: 1.0,
      });
      sentryInitialized = true;
    })
    .catch(() => {
      // Sentry not installed — skip silently
    });
}

export function captureError(error: Error, context?: Record<string, unknown>) {
  console.error('[Astraeus]', error.message, context);

  if (sentryInitialized) {
    // @ts-expect-error — Sentry is an optional dependency
    import('@sentry/nextjs').then((Sentry: { captureException: (e: Error, opts?: Record<string, unknown>) => void }) => {
      Sentry.captureException(error, { extra: context });
    });
  }
}

// --- Web Vitals ---

export function reportWebVitals(metric: {
  name: string;
  value: number;
  id: string;
}) {
  // Report to console in dev, to analytics endpoint in prod
  if (process.env.NODE_ENV === 'development') {
    console.debug(`[WebVital] ${metric.name}: ${metric.value.toFixed(1)}`);
  }

  // In production: POST to /api/vitals or send to OTel collector
  if (process.env.NEXT_PUBLIC_OTEL_ENDPOINT) {
    fetch(`${process.env.NEXT_PUBLIC_OTEL_ENDPOINT}/v1/metrics`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: `web_vital.${metric.name.toLowerCase()}`,
        value: metric.value,
        timestamp: Date.now(),
        attributes: { metric_id: metric.id },
      }),
    }).catch(() => {});
  }
}

// --- Route Performance ---

const routeTimings: Map<string, number> = new Map();

export function startRouteTimer(route: string) {
  routeTimings.set(route, performance.now());
}

export function endRouteTimer(route: string) {
  const start = routeTimings.get(route);
  if (start) {
    const duration = performance.now() - start;
    routeTimings.delete(route);

    if (duration > 2000) {
      console.warn(`[Perf] Route ${route} took ${duration.toFixed(0)}ms (> 2s budget)`);
    }

    return duration;
  }
  return null;
}
