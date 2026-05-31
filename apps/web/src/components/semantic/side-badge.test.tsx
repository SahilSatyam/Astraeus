import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { SideBadge } from './side-badge';

describe('SideBadge', () => {
  it('renders long side uppercased', () => {
    render(<SideBadge side="long" />);
    expect(screen.getByText('long')).toBeInTheDocument();
  });

  it('renders short side', () => {
    render(<SideBadge side="short" />);
    expect(screen.getByText('short')).toBeInTheDocument();
  });

  it('renders flat side', () => {
    render(<SideBadge side="flat" />);
    expect(screen.getByText('flat')).toBeInTheDocument();
  });

  it('renders buy as long-styled', () => {
    render(<SideBadge side="buy" />);
    expect(screen.getByText('buy')).toBeInTheDocument();
  });

  it('renders sell as short-styled', () => {
    render(<SideBadge side="sell" />);
    expect(screen.getByText('sell')).toBeInTheDocument();
  });

  it('applies custom className', () => {
    const { container } = render(<SideBadge side="long" className="extra" />);
    expect(container.firstChild).toHaveClass('extra');
  });
});
