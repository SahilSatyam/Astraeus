'use client';

/**
 * RBAC hook — defensive UI-level role checks.
 *
 * Backend is the authority. This hook only hides UI elements for UX;
 * it never trusts the frontend for security decisions.
 *
 * In scope mode (single-user), the role is always 'operator' with full access.
 * The scaffolding stays for resume-relevance and future multi-user support.
 */

export type Role = 'operator' | 'analyst' | 'viewer';

export interface Permission {
  canTrade: boolean;
  canApproveRecommendations: boolean;
  canArmKillSwitch: boolean;
  canRunAgents: boolean;
  canViewPositions: boolean;
  canViewPnl: boolean;
  canManageStrategies: boolean;
}

const ROLE_PERMISSIONS: Record<Role, Permission> = {
  operator: {
    canTrade: true,
    canApproveRecommendations: true,
    canArmKillSwitch: true,
    canRunAgents: true,
    canViewPositions: true,
    canViewPnl: true,
    canManageStrategies: true,
  },
  analyst: {
    canTrade: false,
    canApproveRecommendations: true,
    canArmKillSwitch: false,
    canRunAgents: true,
    canViewPositions: true,
    canViewPnl: true,
    canManageStrategies: false,
  },
  viewer: {
    canTrade: false,
    canApproveRecommendations: false,
    canArmKillSwitch: false,
    canRunAgents: false,
    canViewPositions: true,
    canViewPnl: false,
    canManageStrategies: false,
  },
};

export function useRbac(): { role: Role; permissions: Permission } {
  // Single-user scope mode — always operator
  const role: Role = 'operator';
  return { role, permissions: ROLE_PERMISSIONS[role] };
}

/**
 * Check if the current user has a specific permission.
 */
export function useHasPermission(key: keyof Permission): boolean {
  const { permissions } = useRbac();
  return permissions[key];
}
