import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { StatusIndicator } from './status-indicator';

describe('StatusIndicator', () => {
  it('renders status text', () => {
    render(<StatusIndicator status="completed" />);
    expect(screen.getByText('completed')).toBeInTheDocument();
  });

  it('renders running status with pulse animation', () => {
    const { container } = render(<StatusIndicator status="running" />);
    const dot = container.querySelector('.animate-pulse');
    expect(dot).not.toBeNull();
  });

  it('renders failed status', () => {
    render(<StatusIndicator status="failed" />);
    expect(screen.getByText('failed')).toBeInTheDocument();
  });

  it('renders order states', () => {
    render(<StatusIndicator status="filled" />);
    expect(screen.getByText('filled')).toBeInTheDocument();
  });

  it('renders unknown status with muted color', () => {
    render(<StatusIndicator status="unknown_status" />);
    expect(screen.getByText('unknown_status')).toBeInTheDocument();
  });

  it('applies custom className', () => {
    const { container } = render(<StatusIndicator status="done" className="my-class" />);
    expect(container.firstChild).toHaveClass('my-class');
  });
});
