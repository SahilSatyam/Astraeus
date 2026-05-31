'use client';

import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { killSwitch } from '@/lib/api-client';
import { useAppStore } from '@/lib/store';
import { Pane } from '@/components/panels/three-pane';

const SCOPES = ['global', 'account:alpaca-paper-1', 'strategy:momentum_xs'];

export default function KillSwitchPage() {
  const { killSwitchArmed, setKillSwitchArmed, activeAccount } = useAppStore();
  const [reason, setReason] = useState('');

  const armMutation = useMutation({
    mutationFn: ({ scope, reason }: { scope: string; reason: string }) =>
      killSwitch.arm(scope, { reason }),
    onSuccess: (_, { scope }) => {
      setKillSwitchArmed(scope, true);
      setReason('');
    },
  });

  const disarmMutation = useMutation({
    mutationFn: (scope: string) => killSwitch.disarm(scope),
    onSuccess: (_, scope) => {
      setKillSwitchArmed(scope, false);
    },
  });

  return (
    <div className="h-full flex flex-col gap-3">
      <div>
        <h1 className="text-base font-semibold">Kill Switches</h1>
        <p className="text-xs text-[var(--color-text-muted)] mt-1">
          Arm to immediately halt all new order submissions for the given scope.
          Sub-second propagation via Redis pub/sub.
        </p>
      </div>

      <Pane title="Switch Controls">
        <div className="space-y-4">
          {SCOPES.map((scope) => {
            const armed = killSwitchArmed[scope] ?? false;
            return (
              <div
                key={scope}
                className={`flex items-center justify-between p-3 rounded border ${
                  armed
                    ? 'border-[var(--color-kill-armed)]/50 bg-[var(--color-kill-armed)]/10'
                    : 'border-[var(--color-border)] bg-[var(--color-bg)]'
                }`}
              >
                <div>
                  <div className="flex items-center gap-2">
                    <span
                      className={`w-3 h-3 rounded-full ${
                        armed ? 'bg-[var(--color-kill-armed)] animate-pulse' : 'bg-[var(--color-kill-disarmed)]'
                      }`}
                    />
                    <span className="text-sm font-medium">{scope}</span>
                  </div>
                  <span className="text-xs text-[var(--color-text-muted)] ml-5">
                    {armed ? 'ARMED — submissions halted' : 'Disarmed — normal operation'}
                  </span>
                </div>

                {armed ? (
                  <button
                    onClick={() => disarmMutation.mutate(scope)}
                    disabled={disarmMutation.isPending}
                    className="px-3 py-1.5 text-xs font-medium rounded bg-[var(--color-kill-disarmed)]/20 text-[var(--color-kill-disarmed)] border border-[var(--color-kill-disarmed)]/30 hover:bg-[var(--color-kill-disarmed)]/30 disabled:opacity-50"
                  >
                    Disarm
                  </button>
                ) : (
                  <button
                    onClick={() => {
                      if (reason.trim()) {
                        armMutation.mutate({ scope, reason });
                      }
                    }}
                    disabled={!reason.trim() || armMutation.isPending}
                    className="px-3 py-1.5 text-xs font-medium rounded bg-[var(--color-kill-armed)]/20 text-[var(--color-kill-armed)] border border-[var(--color-kill-armed)]/30 hover:bg-[var(--color-kill-armed)]/30 disabled:opacity-50"
                  >
                    Arm
                  </button>
                )}
              </div>
            );
          })}

          {/* Reason input */}
          <div className="pt-2 border-t border-[var(--color-border-muted)]">
            <label className="text-xs text-[var(--color-text-muted)] block mb-1">
              Reason (required to arm)
            </label>
            <input
              type="text"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              className="w-full px-3 py-2 text-xs rounded border border-[var(--color-border)] bg-[var(--color-bg)] text-[var(--color-text-primary)]"
              placeholder="e.g. maintenance window, recon drift, manual halt"
            />
          </div>
        </div>
      </Pane>
    </div>
  );
}
