/**
 * Global client state via Zustand.
 *
 * Cross-tree shared state: active account, selected ticker, kill-switch status,
 * command palette open state, connection status.
 */

import { create } from 'zustand';

interface AppState {
  // Active context
  activeAccount: string;
  setActiveAccount: (account: string) => void;

  selectedTicker: string | null;
  setSelectedTicker: (ticker: string | null) => void;

  // Kill switch
  killSwitchArmed: Record<string, boolean>;
  setKillSwitchArmed: (scope: string, armed: boolean) => void;

  // Command palette
  commandPaletteOpen: boolean;
  openCommandPalette: () => void;
  closeCommandPalette: () => void;
  toggleCommandPalette: () => void;

  // Connection status
  wsConnected: boolean;
  setWsConnected: (connected: boolean) => void;

  // Theme
  theme: 'dark' | 'high-contrast' | 'cividis';
  setTheme: (theme: 'dark' | 'high-contrast' | 'cividis') => void;
}

export const useAppStore = create<AppState>((set) => ({
  activeAccount: 'alpaca-paper-1',
  setActiveAccount: (account) => set({ activeAccount: account }),

  selectedTicker: null,
  setSelectedTicker: (ticker) => set({ selectedTicker: ticker }),

  killSwitchArmed: {},
  setKillSwitchArmed: (scope, armed) =>
    set((state) => ({
      killSwitchArmed: { ...state.killSwitchArmed, [scope]: armed },
    })),

  commandPaletteOpen: false,
  openCommandPalette: () => set({ commandPaletteOpen: true }),
  closeCommandPalette: () => set({ commandPaletteOpen: false }),
  toggleCommandPalette: () =>
    set((state) => ({ commandPaletteOpen: !state.commandPaletteOpen })),

  wsConnected: false,
  setWsConnected: (connected) => set({ wsConnected: connected }),

  theme: 'dark',
  setTheme: (theme) => set({ theme }),
}));
