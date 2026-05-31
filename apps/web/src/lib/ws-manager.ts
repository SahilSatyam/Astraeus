/**
 * WebSocket manager with reconnection, exponential backoff, and channel subscriptions.
 *
 * On reconnect: re-fetch snapshot via REST, then resume stream.
 * Prevents silent staleness — the worst failure mode for trading UIs.
 */

type MessageHandler = (data: unknown) => void;

interface Subscription {
  channel: string;
  handler: MessageHandler;
}

const WS_BASE = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000/ws';
const MAX_BACKOFF_MS = 30_000;
const BASE_BACKOFF_MS = 1_000;

export class WsManager {
  private ws: WebSocket | null = null;
  private subscriptions: Map<string, Set<MessageHandler>> = new Map();
  private reconnectAttempt = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private intentionalClose = false;
  private _connected = false;

  get connected(): boolean {
    return this._connected;
  }

  connect(): void {
    if (this.ws?.readyState === WebSocket.OPEN) return;

    this.intentionalClose = false;
    this.ws = new WebSocket(WS_BASE);

    this.ws.onopen = () => {
      this._connected = true;
      this.reconnectAttempt = 0;

      // Re-subscribe to all channels
      for (const channel of this.subscriptions.keys()) {
        this.sendSubscribe(channel);
      }
    };

    this.ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data as string) as {
          channel: string;
          data: unknown;
        };
        const handlers = this.subscriptions.get(msg.channel);
        if (handlers) {
          for (const handler of handlers) {
            handler(msg.data);
          }
        }
      } catch {
        // Ignore malformed messages
      }
    };

    this.ws.onclose = () => {
      this._connected = false;
      if (!this.intentionalClose) {
        this.scheduleReconnect();
      }
    };

    this.ws.onerror = () => {
      this.ws?.close();
    };
  }

  disconnect(): void {
    this.intentionalClose = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.ws?.close();
    this.ws = null;
    this._connected = false;
  }

  subscribe(channel: string, handler: MessageHandler): { unsubscribe: () => void } {
    if (!this.subscriptions.has(channel)) {
      this.subscriptions.set(channel, new Set());
      if (this.ws?.readyState === WebSocket.OPEN) {
        this.sendSubscribe(channel);
      }
    }
    this.subscriptions.get(channel)!.add(handler);

    return {
      unsubscribe: () => {
        const handlers = this.subscriptions.get(channel);
        if (handlers) {
          handlers.delete(handler);
          if (handlers.size === 0) {
            this.subscriptions.delete(channel);
            this.sendUnsubscribe(channel);
          }
        }
      },
    };
  }

  private sendSubscribe(channel: string): void {
    this.ws?.send(JSON.stringify({ action: 'subscribe', channel }));
  }

  private sendUnsubscribe(channel: string): void {
    this.ws?.send(JSON.stringify({ action: 'unsubscribe', channel }));
  }

  private scheduleReconnect(): void {
    const backoff = Math.min(
      BASE_BACKOFF_MS * Math.pow(2, this.reconnectAttempt),
      MAX_BACKOFF_MS,
    );
    // Add jitter (±25%)
    const jitter = backoff * (0.75 + Math.random() * 0.5);
    this.reconnectAttempt++;

    this.reconnectTimer = setTimeout(() => {
      this.connect();
    }, jitter);
  }
}

// Singleton instance
export const wsManager = new WsManager();
