'use client';

import { useEffect, useState } from 'react';
import { z } from 'zod';
import { wsManager } from '@/lib/ws-manager';

/**
 * Subscribe to a WebSocket channel with Zod schema validation.
 * Messages that fail validation are silently dropped.
 */
export function useWsChannel<T>(channel: string, schema: z.ZodSchema<T>, maxItems = 100) {
  const [state, setState] = useState<T[]>([]);

  useEffect(() => {
    // Ensure WS is connected
    wsManager.connect();

    const sub = wsManager.subscribe(channel, (msg) => {
      const parsed = schema.safeParse(msg);
      if (parsed.success) {
        setState((prev) => {
          const next = [...prev, parsed.data];
          // Ring buffer — keep last N items
          return next.length > maxItems ? next.slice(-maxItems) : next;
        });
      }
    });

    return () => sub.unsubscribe();
  }, [channel, schema, maxItems]);

  return state;
}
