import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { Delta } from './delta';

describe('Delta', () => {
  it('renders positive value with + prefix', () => {
    render(<Delta value={2.5} />);
    const el = screen.getByText('+2.50');
    expect(el).toBeInTheDocument();
    expect(el.className).toContain('text-positive');
  });

  it('renders negative value with - prefix', () => {
    render(<Delta value={-1.3} />);
    const el = screen.getByText('-1.30');
    expect(el).toBeInTheDocument();
    expect(el.className).toContain('text-negative');
  });

  it('renders zero value as neutral', () => {
    render(<Delta value={0} />);
    const el = screen.getByText('0.00');
    expect(el).toBeInTheDocument();
    expect(el.className).toContain('text-muted');
  });

  it('respects custom decimals', () => {
    render(<Delta value={3.14159} decimals={3} />);
    expect(screen.getByText('+3.142')).toBeInTheDocument();
  });

  it('renders percent format', () => {
    render(<Delta value={0.0534} format="percent" />);
    expect(screen.getByText('+5.34%')).toBeInTheDocument();
  });
});
