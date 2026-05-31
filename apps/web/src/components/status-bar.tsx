'use client';

import { useAppStore } from '@/lib/store';

/**
 * Bottom status bar — always visible.
 * Shows: connection state, kill-switch status, active account, keyboard hint.
 */
export function StatusBar() {
  const { wsConnected, killSwitchArmed, activeAccount } = useAppStore();

  const globalArmed = killSwitchArmed['global'] ?? false;
  const accountArmed = killSwitchArmed[`account:${activeAccount}`] ?? false;
  const anyArmed = globalArmed || accountArmed;

  return (
    <footer className="h-6 flex items-center justify-between px-3 border-t border-[var(--color-border)] bg-[var(--color-bg-elevated)] text-[11px] text-[var(--color-text-muted)] select-none">
      {/* Left */}
      <div className="flex items-center gap-4">
        {/* Connection */}
        <span className="flex items-center gap-1">
          <span
            className={`w-1.5 h-1.5 rounded-full ${
              wsConnected ? 'bg-[var(--color-status-active)]' : 'bg-[var(--color-status-error)]'
            }`}
          />
          {wsConnected ? 'Connected' : 'Disconnected'}
        </span>

        {/* Kill switch */}
        {anyArmed && (
          <span className="flex items-center gap-1 text-[var(--color-kill-armed)] font-semibold">
            ⚠ KILL SWITCH ARMED
            {globalArmed ? ' (GLOBAL)' : ` (${activeAccount})`}
          </span>
        )}
      </div>

      {/* Right */}
      <div className="flex items-center gap-4">
        <span>Account: {activeAccount}</span>
        <span>
          <kbd className="px-1 py-0.5 rounded bg-[var(--color-bg-surface)] text-[10px]">⌘K</kbd>{' '}
          Command Palette
        </span>
      </div>
    </footer>
  );
}
