import type { Meta, StoryObj } from '@storybook/react';
import { RegimePill } from './regime-pill';

const meta: Meta<typeof RegimePill> = {
  title: 'Semantic/RegimePill',
  component: RegimePill,
  tags: ['autodocs'],
};

export default meta;
type Story = StoryObj<typeof RegimePill>;

export const RiskOn: Story = { args: { label: 'risk_on', probability: 0.87 } };
export const RiskOff: Story = { args: { label: 'risk_off', probability: 0.72 } };
export const VolSpike: Story = { args: { label: 'vol_spike', probability: 0.91 } };
export const MeanReversion: Story = { args: { label: 'mean_reversion', probability: 0.65 } };
export const Trending: Story = { args: { label: 'trending', probability: 0.78 } };
export const Uncertain: Story = { args: { label: 'uncertain', probability: 0.45 } };
