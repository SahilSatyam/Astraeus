import type { Meta, StoryObj } from '@storybook/react';
import { Pane, TwoPane, ThreePane } from './three-pane';

const meta: Meta<typeof Pane> = {
  title: 'Layout/Pane',
  component: Pane,
  tags: ['autodocs'],
};

export default meta;
type Story = StoryObj<typeof Pane>;

export const SinglePane: Story = {
  args: { title: 'Sample Pane' },
  render: (args) => (
    <div style={{ height: 200 }}>
      <Pane {...args}>
        <p className="text-xs text-[var(--color-text-secondary)]">Content goes here</p>
      </Pane>
    </div>
  ),
};

export const TwoPaneVertical: Story = {
  render: () => (
    <div style={{ height: 300 }}>
      <TwoPane split="vertical" ratio="1fr 2fr">
        <Pane title="Left">Left content</Pane>
        <Pane title="Right">Right content</Pane>
      </TwoPane>
    </div>
  ),
};

export const ThreePaneLayout: Story = {
  render: () => (
    <div style={{ height: 400 }}>
      <ThreePane>
        <Pane title="Pane 1">First</Pane>
        <Pane title="Pane 2">Second</Pane>
        <Pane title="Pane 3">Third (full width)</Pane>
      </ThreePane>
    </div>
  ),
};
