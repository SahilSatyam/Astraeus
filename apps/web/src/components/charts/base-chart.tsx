'use client';

import { useRef, useEffect } from 'react';
import type { EChartsOption, ECharts } from 'echarts';

/**
 * Base ECharts wrapper — dynamic import to avoid bundle bloat.
 * All chart components build on this.
 */
export function BaseChart({
  option,
  height = '100%',
  className = '',
  onReady,
}: {
  option: EChartsOption;
  height?: string | number;
  className?: string;
  onReady?: (instance: ECharts) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<ECharts | null>(null);

  useEffect(() => {
    let instance: ECharts | null = null;

    async function init() {
      if (!containerRef.current) return;
      const echarts = await import('echarts');
      instance = echarts.init(containerRef.current, 'dark', { renderer: 'canvas' });
      chartRef.current = instance;
      instance.setOption(option);
      onReady?.(instance);
    }

    init();

    return () => {
      instance?.dispose();
      chartRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Update option when it changes
  useEffect(() => {
    if (chartRef.current) {
      chartRef.current.setOption(option, { notMerge: false });
    }
  }, [option]);

  // Handle resize
  useEffect(() => {
    function onResize() {
      chartRef.current?.resize();
    }
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  return (
    <div
      ref={containerRef}
      className={className}
      style={{ height, width: '100%' }}
    />
  );
}
