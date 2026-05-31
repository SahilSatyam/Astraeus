import { describe, it, expect, beforeEach } from 'vitest';
import { useAppStore } from './store';

describe('AppStore', () => {
  beforeEach(() => {
    // Reset store between tests
    useAppStore.setState({
      activeAccount: 'alpaca-paper-1',
      selectedTicker: null,
      killSwitchArmed: {},
      commandPaletteOpen: false,
      wsConnected: false,
      theme: 'dark',
    });
  });

  it('has correct default state', () => {
    const state = useAppStore.getState();
    expect(state.activeAccount).toBe('alpaca-paper-1');
    expect(state.selectedTicker).toBeNull();
    expect(state.commandPaletteOpen).toBe(false);
    expect(state.wsConnected).toBe(false);
    expect(state.theme).toBe('dark');
  });

  it('sets active account', () => {
    useAppStore.getState().setActiveAccount('ibkr-live-1');
    expect(useAppStore.getState().activeAccount).toBe('ibkr-live-1');
  });

  it('sets selected ticker', () => {
    useAppStore.getState().setSelectedTicker('AAPL');
    expect(useAppStore.getState().selectedTicker).toBe('AAPL');
  });

  it('toggles command palette', () => {
    expect(useAppStore.getState().commandPaletteOpen).toBe(false);
    useAppStore.getState().toggleCommandPalette();
    expect(useAppStore.getState().commandPaletteOpen).toBe(true);
    useAppStore.getState().toggleCommandPalette();
    expect(useAppStore.getState().commandPaletteOpen).toBe(false);
  });

  it('manages kill switch state per scope', () => {
    useAppStore.getState().setKillSwitchArmed('global', true);
    expect(useAppStore.getState().killSwitchArmed['global']).toBe(true);

    useAppStore.getState().setKillSwitchArmed('account:alpaca-paper-1', true);
    expect(useAppStore.getState().killSwitchArmed['account:alpaca-paper-1']).toBe(true);
    expect(useAppStore.getState().killSwitchArmed['global']).toBe(true);

    useAppStore.getState().setKillSwitchArmed('global', false);
    expect(useAppStore.getState().killSwitchArmed['global']).toBe(false);
  });

  it('sets theme', () => {
    useAppStore.getState().setTheme('high-contrast');
    expect(useAppStore.getState().theme).toBe('high-contrast');
  });

  it('sets ws connected', () => {
    useAppStore.getState().setWsConnected(true);
    expect(useAppStore.getState().wsConnected).toBe(true);
  });
});
