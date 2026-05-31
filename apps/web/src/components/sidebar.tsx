'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

interface NavItem {
  label: string;
  href: string;
  icon: string;
  group: string;
}

const NAV_ITEMS: NavItem[] = [
  // Research
  { label: 'Data Health', href: '/research/data-health', icon: '📊', group: 'Research' },
  { label: 'Features', href: '/research/features', icon: '🧮', group: 'Research' },
  { label: 'News & Sentiment', href: '/research/news', icon: '📰', group: 'Research' },
  { label: 'AI Copilot', href: '/research/copilot', icon: '🤖', group: 'Research' },

  // Quant
  { label: 'Backtests', href: '/quant/backtests', icon: '📈', group: 'Quant' },
  { label: 'Optimization', href: '/quant/optimization', icon: '⚙️', group: 'Quant' },

  // Portfolio
  { label: 'Holdings', href: '/portfolio/holdings', icon: '💼', group: 'Portfolio' },
  { label: 'Exposures', href: '/portfolio/exposures', icon: '📐', group: 'Portfolio' },
  { label: 'Attribution', href: '/portfolio/attribution', icon: '🎯', group: 'Portfolio' },

  // Recommendations
  { label: 'Approve', href: '/recommendations/approve', icon: '✅', group: 'Recommendations' },

  // Trading
  { label: 'Orders', href: '/trading/orders', icon: '📋', group: 'Trading' },
  { label: 'Positions', href: '/trading/positions', icon: '📊', group: 'Trading' },
  { label: 'PnL', href: '/trading/pnl', icon: '💰', group: 'Trading' },

  // Operator
  { label: 'Kill Switch', href: '/operator/kill-switch', icon: '🛑', group: 'Operator' },
  { label: 'Reconciliation', href: '/operator/recon', icon: '🔄', group: 'Operator' },
];

export function Sidebar() {
  const pathname = usePathname();

  const groups = [...new Set(NAV_ITEMS.map((item) => item.group))];

  return (
    <aside className="w-52 flex-shrink-0 border-r border-[var(--color-border)] bg-[var(--color-bg-surface)] overflow-y-auto">
      {/* Logo */}
      <div className="px-4 py-3 border-b border-[var(--color-border-muted)]">
        <h1 className="text-sm font-bold text-[var(--color-text-primary)] tracking-tight">
          ASTRAEUS
        </h1>
        <p className="text-[10px] text-[var(--color-text-muted)]">Operator Terminal</p>
      </div>

      {/* Navigation */}
      <nav className="py-2">
        {groups.map((group) => (
          <div key={group} className="mb-2">
            <h2 className="px-4 py-1 text-[10px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
              {group}
            </h2>
            {NAV_ITEMS.filter((item) => item.group === group).map((item) => {
              const active = pathname === item.href || pathname?.startsWith(item.href + '/');
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`flex items-center gap-2 px-4 py-1.5 text-xs transition-colors ${
                    active
                      ? 'bg-[var(--color-bg-elevated)] text-[var(--color-text-primary)] border-r-2 border-[var(--color-status-info)]'
                      : 'text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)] hover:bg-[var(--color-bg-elevated)]'
                  }`}
                >
                  <span className="text-sm">{item.icon}</span>
                  <span>{item.label}</span>
                </Link>
              );
            })}
          </div>
        ))}
      </nav>
    </aside>
  );
}
