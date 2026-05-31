/**
 * Feature flags — controls module visibility.
 *
 * All eight modules live behind feature flags per the Phase 9 definition of done.
 * In scope mode, all flags default to true. In production, these would be
 * backed by a remote config service (LaunchDarkly, Unleash, or env vars).
 */

export interface FeatureFlags {
  dataHealth: boolean;
  featureCatalog: boolean;
  backtests: boolean;
  portfolio: boolean;
  researchTerminal: boolean;
  aiCopilot: boolean;
  recommendations: boolean;
  trading: boolean;
  operatorConsole: boolean;
}

const DEFAULT_FLAGS: FeatureFlags = {
  dataHealth: true,
  featureCatalog: true,
  backtests: true,
  portfolio: true,
  researchTerminal: true,
  aiCopilot: true,
  recommendations: true,
  trading: true,
  operatorConsole: true,
};

/**
 * Get current feature flags.
 * Reads from environment variables with fallback to defaults.
 */
export function getFeatureFlags(): FeatureFlags {
  if (typeof window === 'undefined') {
    // Server-side: read from env
    return {
      dataHealth: envFlag('NEXT_PUBLIC_FF_DATA_HEALTH', true),
      featureCatalog: envFlag('NEXT_PUBLIC_FF_FEATURE_CATALOG', true),
      backtests: envFlag('NEXT_PUBLIC_FF_BACKTESTS', true),
      portfolio: envFlag('NEXT_PUBLIC_FF_PORTFOLIO', true),
      researchTerminal: envFlag('NEXT_PUBLIC_FF_RESEARCH_TERMINAL', true),
      aiCopilot: envFlag('NEXT_PUBLIC_FF_AI_COPILOT', true),
      recommendations: envFlag('NEXT_PUBLIC_FF_RECOMMENDATIONS', true),
      trading: envFlag('NEXT_PUBLIC_FF_TRADING', true),
      operatorConsole: envFlag('NEXT_PUBLIC_FF_OPERATOR_CONSOLE', true),
    };
  }

  // Client-side: NEXT_PUBLIC_ vars are inlined at build time
  return DEFAULT_FLAGS;
}

function envFlag(key: string, defaultValue: boolean): boolean {
  const val = process.env[key];
  if (val === undefined) return defaultValue;
  return val === 'true' || val === '1';
}

/**
 * Check if a specific module is enabled.
 */
export function isModuleEnabled(module: keyof FeatureFlags): boolean {
  return getFeatureFlags()[module];
}
