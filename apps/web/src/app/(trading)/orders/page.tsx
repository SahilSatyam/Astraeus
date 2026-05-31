'use client';

import { useQuery } from '@tanstack/react-query';
import { oms, type OrderResponse } from '@/lib/api-client';
import { useAppStore } from '@/lib/store';
import { Pane, TwoPane } from '@/components/panels/three-pane';
import { SideBadge } from '@/components/semantic/side-badge';
import { StatusIndicator } from '@/components/semantic/status-indicator';
import { formatTime } from '@/lib/formatters';
import { useWsChannel } from '@/hooks/use-ws-channel';
import { z } from 'zod';

const orderEventSchema = z.object({
  order_id: z.string(),
  event_type: z.string(),
  occurred_at: z.string(),
  payload: z.record(z.string(), z.unknown()),
});

export default function OrdersPage() {
  const { activeAccount } = useAppStore();

  const { data: orders, isLoading } = useQuery({
    queryKey: ['oms', 'orders', activeAccount],
    queryFn: () => oms.getOrders({ account_id: activeAccount }),
    refetchInterval: 5000, // Fallback polling for orders
  });

  // Live order events via WebSocket
  const liveEvents = useWsChannel(
    `oms.events.${activeAccount}`,
    orderEventSchema,
    50,
  );

  return (
    <div className="h-full flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <h1 className="text-base font-semibold">Orders</h1>
        <span className="text-xs text-[var(--color-text-muted)]">
          Account: {activeAccount}
        </span>
      </div>

      <TwoPane split="vertical" ratio="2fr 1fr">
        <Pane title="Order Book">
          {isLoading ? (
            <div className="text-sm text-[var(--color-text-muted)]">Loading...</div>
          ) : (
            <OrderTable orders={orders ?? []} />
          )}
        </Pane>

        <Pane title="Live Events">
          <div className="space-y-1 font-mono text-[11px]">
            {liveEvents.length === 0 && (
              <div className="text-[var(--color-text-muted)] text-center py-4">
                Waiting for events...
              </div>
            )}
            {liveEvents.map((event, i) => (
              <div
                key={i}
                className="flex items-center gap-2 py-0.5 border-b border-[var(--color-border-muted)]"
              >
                <span className="text-[var(--color-text-muted)]">
                  {formatTime(event.occurred_at)}
                </span>
                <StatusIndicator status={event.event_type} />
                <span className="text-[var(--color-text-secondary)] truncate">
                  {event.order_id.slice(0, 8)}
                </span>
              </div>
            ))}
          </div>
        </Pane>
      </TwoPane>
    </div>
  );
}

function OrderTable({ orders }: { orders: OrderResponse[] }) {
  return (
    <div className="overflow-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-[var(--color-border-muted)] text-[var(--color-text-muted)]">
            <th className="text-left py-1.5 px-2">Symbol</th>
            <th className="text-left py-1.5 px-2">Side</th>
            <th className="text-right py-1.5 px-2">Qty</th>
            <th className="text-left py-1.5 px-2">State</th>
            <th className="text-left py-1.5 px-2">Broker ID</th>
            <th className="text-left py-1.5 px-2">Created</th>
          </tr>
        </thead>
        <tbody>
          {orders.map((order) => (
            <tr
              key={order.order_id}
              className="border-b border-[var(--color-border-muted)] hover:bg-[var(--color-bg-elevated)]"
            >
              <td className="py-1.5 px-2 font-semibold">{order.symbol}</td>
              <td className="py-1.5 px-2">
                <SideBadge side={order.side as 'buy' | 'sell'} />
              </td>
              <td className="py-1.5 px-2 text-right font-mono tabular-nums">{order.qty}</td>
              <td className="py-1.5 px-2">
                <StatusIndicator status={order.state} />
              </td>
              <td className="py-1.5 px-2 font-mono text-[var(--color-text-muted)]">
                {order.broker_order_id?.slice(0, 8) ?? '—'}
              </td>
              <td className="py-1.5 px-2 text-[var(--color-text-muted)]">
                {formatTime(order.created_at)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {orders.length === 0 && (
        <div className="text-center py-8 text-sm text-[var(--color-text-muted)]">
          No orders
        </div>
      )}
    </div>
  );
}
