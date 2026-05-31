import type { Preview } from '@storybook/react';
import '../src/app/globals.css';
import '../src/styles/tokens.css';

const preview: Preview = {
  parameters: {
    backgrounds: {
      default: 'dark',
      values: [
        { name: 'dark', value: '#0d1117' },
        { name: 'surface', value: '#161b22' },
      ],
    },
  },
};

export default preview;
