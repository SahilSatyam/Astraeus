'use client';

import { useEffect, useRef, useState } from 'react';

/**
 * Subscribe to a Server-Sent Events stream.
 * Ideal for log-style append data (agent step logs, order events).
 */
export function useSseStream<T>(url: string | null, parse?: (data: string) => T) {
  const [events, setEvents] = useState<T[]>([]);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const sourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!url) return;

    const source = new EventSource(url);
    sourceRef.current = source;

    source.onopen = () => {
      setConnected(true);
      setError(null);
    };

    source.onmessage = (event) => {
      try {
        const parsed = parse
          ? parse(event.data)
          : (JSON.parse(event.data) as T);
        setEvents((prev) => [...prev, parsed]);
      } catch {
        // Skip malformed events
      }
    };

    source.onerror = () => {
      setConnected(false);
      setError('SSE connection lost');
      source.close();
    };

    return () => {
      source.close();
      sourceRef.current = null;
    };
  }, [url, parse]);

  const clear = () => setEvents([]);

  return { events, connected, error, clear };
}
