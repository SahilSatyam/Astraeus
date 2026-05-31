'use client';

import { ReactNode } from 'react';

interface PaneProps {
  title: string;
  children: ReactNode;
  className?: string;
}

export function Pane({ title, children, className = '' }: PaneProps) {
  return (
    <div
      className={`flex flex-col border border-[var(--color-border)] rounded bg-[var(--color-bg-surface)] overflow-hidden ${className}`}
    >
      <div className="px-3 py-1.5 border-b border-[var(--color-border-muted)] bg-[var(--color-bg-elevated)]">
        <h3 className="text-xs font-medium uppercase tracking-wide text-[var(--color-text-secondary)]">
          {title}
        </h3>
      </div>
      <div className="flex-1 overflow-auto p-3">{children}</div>
    </div>
  );
}

interface ThreePaneProps {
  children: ReactNode;
  layout?: 'horizontal' | 'top-bottom';
}

/**
 * Three-pane terminal layout.
 * Default: two panes on top, one full-width on bottom.
 */
export function ThreePane({ children, layout = 'top-bottom' }: ThreePaneProps) {
  if (layout === 'horizontal') {
    return <div className="grid grid-cols-3 gap-2 h-full">{children}</div>;
  }

  return (
    <div className="grid grid-rows-[1fr_1fr] gap-2 h-full">
      <div className="grid grid-cols-2 gap-2">{children}</div>
    </div>
  );
}

interface TwoPaneProps {
  children: ReactNode;
  split?: 'vertical' | 'horizontal';
  ratio?: string;
}

/**
 * Two-pane layout with configurable split direction and ratio.
 */
export function TwoPane({ children, split = 'vertical', ratio = '1fr 1fr' }: TwoPaneProps) {
  const style =
    split === 'vertical'
      ? { gridTemplateColumns: ratio }
      : { gridTemplateRows: ratio };

  return (
    <div className="grid gap-2 h-full" style={style}>
      {children}
    </div>
  );
}
