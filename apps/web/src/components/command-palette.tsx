'use client';

import { useCallback, useEffect } from 'react';
import { Command } from 'cmdk';
import { useRouter } from 'next/navigation';
import { useAppStore } from '@/lib/store';
import { useKeyboardShortcut } from '@/hooks/use-keyboard-shortcut';

interface CommandItem {
  id: string;
  label: string;
  shortcut?: string;
  action: () => void;
  group: string;
}

/**
 * Command palette (⌘K / Ctrl+K).
 * Covers 90% of routine operator actions: navigation, kill-switch, account switch.
 */
export function CommandPalette() {
  const router = useRouter();
  const { commandPaletteOpen, closeCommandPalette, toggleCommandPalette } = useAppStore();

  useKeyboardShortcut({ key: 'k', ctrl: true }, toggleCommandPalette);

  // Close on Escape
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape' && commandPaletteOpen) {
        closeCommandPalette();
      }
    }
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [commandPaletteOpen, closeCommandPalette]);

  const navigate = useCallback(
    (path: string) => {
      router.push(path);
      closeCommandPalette();
    },
    [router, closeCommandPalette],
  );

  const commands: CommandItem[] = [
    // Navigation
    { id: 'nav-portfolio', label: 'Go to Portfolio', shortcut: 'g p', action: () => navigate('/portfolio/holdings'), group: 'Navigation' },
    { id: 'nav-trading', label: 'Go to Trading', shortcut: 'g t', action: () => navigate('/trading/orders'), group: 'Navigation' },
    { id: 'nav-recommendations', label: 'Go to Recommendations', shortcut: 'g r', action: () => navigate('/recommendations/approve'), group: 'Navigation' },
    { id: 'nav-copilot', label: 'Go to AI Copilot', shortcut: 'g c', action: () => navigate('/research/copilot'), group: 'Navigation' },
    { id: 'nav-data-health', label: 'Go to Data Health', shortcut: 'g d', action: () => navigate('/research/data-health'), group: 'Navigation' },
    { id: 'nav-backtests', label: 'Go to Backtests', shortcut: 'g b', action: () => navigate('/quant/backtests'), group: 'Navigation' },
    { id: 'nav-kill-switch', label: 'Go to Kill Switch', shortcut: 'g k', action: () => navigate('/operator/kill-switch'), group: 'Navigation' },
    { id: 'nav-recon', label: 'Go to Reconciliation', shortcut: 'g n', action: () => navigate('/operator/recon'), group: 'Navigation' },

    // Actions
    { id: 'action-kill-global', label: 'Arm Global Kill Switch', action: () => navigate('/operator/kill-switch'), group: 'Actions' },
    { id: 'action-replay', label: 'Trigger Pipeline Replay', action: () => navigate('/recommendations/approve'), group: 'Actions' },
  ];

  if (!commandPaletteOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-[20vh]">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/60"
        onClick={closeCommandPalette}
      />

      {/* Palette */}
      <Command
        className="relative w-full max-w-lg rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-elevated)] shadow-2xl overflow-hidden"
        label="Command palette"
      >
        <Command.Input
          className="w-full px-4 py-3 text-sm bg-transparent border-b border-[var(--color-border-muted)] text-[var(--color-text-primary)] placeholder:text-[var(--color-text-muted)] outline-none"
          placeholder="Type a command or search..."
          autoFocus
        />
        <Command.List className="max-h-80 overflow-y-auto p-2">
          <Command.Empty className="px-4 py-6 text-center text-sm text-[var(--color-text-muted)]">
            No results found.
          </Command.Empty>

          {['Navigation', 'Actions'].map((group) => (
            <Command.Group
              key={group}
              heading={group}
              className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:text-[var(--color-text-muted)]"
            >
              {commands
                .filter((c) => c.group === group)
                .map((cmd) => (
                  <Command.Item
                    key={cmd.id}
                    value={cmd.label}
                    onSelect={cmd.action}
                    className="flex items-center justify-between px-3 py-2 rounded text-sm text-[var(--color-text-primary)] cursor-pointer data-[selected=true]:bg-[var(--color-bg-surface)]"
                  >
                    <span>{cmd.label}</span>
                    {cmd.shortcut && (
                      <kbd className="text-xs text-[var(--color-text-muted)] font-mono">
                        {cmd.shortcut}
                      </kbd>
                    )}
                  </Command.Item>
                ))}
            </Command.Group>
          ))}
        </Command.List>
      </Command>
    </div>
  );
}
