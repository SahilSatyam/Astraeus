import type { Meta, StoryObj } from '@storybook/react';
import { Delta } from './delta';

const meta: Meta<typeof Delta> = {
  title: 'Semantic/Delta',
  component: Delta,
  tags: ['autodocs'],
  argTypes: {
    format: { control: 'radio', options: ['number', 'percent'] },
  },
};

export default meta;
type Story = StoryObj<typeof Delta>;

export const Positive: Story = {
  args: { value: 1234.56, format: 'number', decimals: 2 },
};

export const Negative: Story = {
  args: { value: -567.89, format: 'number', decimals: 2 },
};

export const Zero: Story = {
  args: { value: 0, format: 'number', decimals: 2 },
};

export const PercentPositive: Story = {
  args: { value: 0.0534, format: 'percent', decimals: 2 },
};

export const PercentNegative: Story = {
  args: { value: -0.0212, format: 'percent', decimals: 2 },
};
