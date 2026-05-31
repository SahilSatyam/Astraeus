import { describe, it, expect } from 'vitest';
import {
  formatNumber,
  formatPercent,
  formatBps,
  formatUsd,
  formatDelta,
  formatDeltaPercent,
  deltaColor,
  formatDuration,
  truncate,
} from './formatters';

describe('formatNumber', () => {
  it('formats with thousands separators', () => {
    expect(formatNumber(1234567.89)).toBe('1,234,567.89');
  });

  it('respects decimal places', () => {
    expect(formatNumber(3.14159, 3)).toBe('3.142');
  });

  it('handles zero', () => {
    expect(formatNumber(0)).toBe('0.00');
  });

  it('handles negative', () => {
    expect(formatNumber(-42.5, 1)).toBe('-42.5');
  });
});

describe('formatPercent', () => {
  it('converts decimal to percentage', () => {
    expect(formatPercent(0.0534)).toBe('5.34%');
  });

  it('handles negative', () => {
    expect(formatPercent(-0.12)).toBe('-12.00%');
  });

  it('handles zero', () => {
    expect(formatPercent(0)).toBe('0.00%');
  });
});

describe('formatBps', () => {
  it('converts to basis points', () => {
    expect(formatBps(0.0001)).toBe('1.0 bps');
  });

  it('handles larger values', () => {
    expect(formatBps(0.005)).toBe('50.0 bps');
  });
});

describe('formatUsd', () => {
  it('formats positive USD', () => {
    expect(formatUsd(1234.56)).toBe('$1,234.56');
  });

  it('formats negative USD', () => {
    expect(formatUsd(-500)).toBe('-$500.00');
  });

  it('handles zero', () => {
    expect(formatUsd(0)).toBe('$0.00');
  });
});

describe('formatDelta', () => {
  it('adds + prefix for positive', () => {
    expect(formatDelta(42.5)).toBe('+42.50');
  });

  it('keeps - prefix for negative', () => {
    expect(formatDelta(-10.3)).toBe('-10.30');
  });

  it('no prefix for zero', () => {
    expect(formatDelta(0)).toBe('0.00');
  });
});

describe('formatDeltaPercent', () => {
  it('formats positive delta percent', () => {
    expect(formatDeltaPercent(0.05)).toBe('+5.00%');
  });

  it('formats negative delta percent', () => {
    expect(formatDeltaPercent(-0.032)).toBe('-3.20%');
  });
});

describe('deltaColor', () => {
  it('returns positive class for positive values', () => {
    expect(deltaColor(1)).toBe('text-positive');
  });

  it('returns negative class for negative values', () => {
    expect(deltaColor(-1)).toBe('text-negative');
  });

  it('returns muted class for zero', () => {
    expect(deltaColor(0)).toBe('text-muted');
  });
});

describe('formatDuration', () => {
  it('formats milliseconds', () => {
    expect(formatDuration(500)).toBe('500ms');
  });

  it('formats seconds', () => {
    expect(formatDuration(2500)).toBe('2.5s');
  });

  it('formats minutes', () => {
    expect(formatDuration(90000)).toBe('1.5m');
  });
});

describe('truncate', () => {
  it('returns short strings unchanged', () => {
    expect(truncate('hello', 10)).toBe('hello');
  });

  it('truncates long strings with ellipsis', () => {
    expect(truncate('hello world', 8)).toBe('hello w…');
  });

  it('handles exact length', () => {
    expect(truncate('hello', 5)).toBe('hello');
  });
});
