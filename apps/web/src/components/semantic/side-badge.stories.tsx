import type { Meta, StoryObj } from '@storybook/react';
import { SideBadge } from './side-badge';

const meta: Meta<typeof SideBadge> = {
  title: 'Semantic/SideBadge',
  component: SideBadge,
  tags: ['autodocs'],
};

export default meta;
type Story = StoryObj<typeof SideBadge>;

export const Long: Story = { args: { side: 'long' } };
export const Short: Story = { args: { side: 'short' } };
export const Flat: Story = { args: { side: 'flat' } };
export const Buy: Story = { args: { side: 'buy' } };
export const Sell: Story = { args: { side: 'sell' } };
