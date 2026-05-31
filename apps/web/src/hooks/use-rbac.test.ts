import { describe, it, expect } from 'vitest';
import { renderHook } from '@testing-library/react';
import { useRbac, useHasPermission } from './use-rbac';

describe('useRbac', () => {
  it('returns operator role in scope mode', () => {
    const { result } = renderHook(() => useRbac());
    expect(result.current.role).toBe('operator');
  });

  it('operator has full permissions', () => {
    const { result } = renderHook(() => useRbac());
    const { permissions } = result.current;

    expect(permissions.canTrade).toBe(true);
    expect(permissions.canApproveRecommendations).toBe(true);
    expect(permissions.canArmKillSwitch).toBe(true);
    expect(permissions.canRunAgents).toBe(true);
    expect(permissions.canViewPositions).toBe(true);
    expect(permissions.canViewPnl).toBe(true);
    expect(permissions.canManageStrategies).toBe(true);
  });
});

describe('useHasPermission', () => {
  it('returns true for operator trading permission', () => {
    const { result } = renderHook(() => useHasPermission('canTrade'));
    expect(result.current).toBe(true);
  });

  it('returns true for kill switch permission', () => {
    const { result } = renderHook(() => useHasPermission('canArmKillSwitch'));
    expect(result.current).toBe(true);
  });
});
