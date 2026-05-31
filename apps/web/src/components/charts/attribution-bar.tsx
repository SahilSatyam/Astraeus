'use client';

import { useMemo } from 'react';
import type { EChartsOption } from 'echarts';
import { BaseChart } from './base-chart';

export interface AttributionItem {
  label: string;
  value: number;
}

interface AttributionBarProps {
  data: AttributionItem[];
  height?: string | number;
  title?: string;
  className?: string;
}

/**
 * Horizontal bar chart for attribution (factor, sector, signal contribution).
 * Bars colored green/red based on positive/negative values.
 */
export function AttributionBar({
  data,
  height = 250,
  title,
  className = '',
}: AttributionBarProps) {
  const option = useMemo<EChartsOption>(() => {
    const sorted = [...data].sort((a, b) => b.value - a.value);
    const labels = sorted.map((d) => d.label);
    const values = sorted.map((d) => d.value);

    return {
      backgroundColor: 'transparent',
      title: title
        ? { text: title, textStyle: { color: '#8b949e', fontSize: 11, fontWeight: 'normal' }, left: 0, top: 0 }
        : undefined,
      grid: { left: 100, right: 40, top: title ? 30 : 10, bottom: 10 },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        backgroundColor: '#1c2128',
        borderColor: '#30363d',
        textStyle: { color: '#e6edf3', fontSize: 11 },
        formatter: (params: unknown) => {
          const p = (params as Array<{ name: string; value: number }>)[0];
          return `${p.name}: ${(p.value * 100).toFixed(2)}%`;
        },
      },
      xAxis: {
        type: 'value',
        axisLine: { lineStyle: { color: '#30363d' } },
        axisLabel: {
          color: '#6e7681',
          fontSize: 10,
          formatter: (v: number) => `${(v * 100).toFixed(0)}%`,
        },
        splitLine: { lineStyle: { color: '#21262d' } },
      },
      yAxis: {
        type: 'category',
        data: labels,
        axisLine: { show: false },
        axisLabel: { color: '#e6edf3', fontSize: 11 },
        axisTick: { show: false },
      },
      series: [
        {
          type: 'bar',
          data: values.map((v) => ({
            value: v,
            itemStyle: { color: v >= 0 ? '#3fb950' : '#f85149' },
          })),
          barWidth: '60%',
        },
      ],
    };
  }, [data, title]);

  return <BaseChart option={option} height={height} className={className} />;
}
