import type { Meta, StoryObj } from '@storybook/react';
import { StatusIndicator } from './status-indicator';

const meta: Meta<typeof StatusIndicator> = {
  title: 'Semantic/StatusIndicator',
  component: StatusIndicator,
  tags: ['autodocs'],
};

export default meta;
type Story = StoryObj<typeof StatusIndicator>;

export const Running: Story = { args: { status: 'running' } };
export const Completed: Story = { args: { status: 'completed' } };
export const Failed: Story = { args: { status: 'failed' } };
export const Degraded: Story = { args: { status: 'degraded' } };
export const Pending: Story = { args: { status: 'pending' } };
export const Filled: Story = { args: { status: 'filled' } };
export const Rejected: Story = { args: { status: 'rejected' } };
export const Connected: Story = { args: { status: 'connected' } };
export const Disconnected: Story = { args: { status: 'disconnected' } };
