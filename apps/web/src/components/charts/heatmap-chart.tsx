'use client';

import { useMemo } from 'react';
import type { EChartsOption } from 'echarts';
import { BaseChart } from './base-chart';

export interface HeatmapCell {
  x: string;
  y: string;
  value: number;
}

interface HeatmapChartProps {
  data: HeatmapCell[];
  xLabels: string[];
  yLabels: string[];
  height?: string | number;
  title?: string;
  className?: string;
}

/**
 * Heatmap chart — used for correlation matrices, sentiment grids, sector exposure.
 */
export function HeatmapChart({
  data,
  xLabels,
  yLabels,
  height = 300,
  title,
  className = '',
}: HeatmapChartProps) {
  const option = useMemo<EChartsOption>(() => {
    const seriesData = data.map((cell) => [
      xLabels.indexOf(cell.x),
      yLabels.indexOf(cell.y),
      cell.value,
    ]);

    const values = data.map((d) => d.value);
    const min = Math.min(...values);
    const max = Math.max(...values);

    return {
      backgroundColor: 'transparent',
      title: title
        ? { text: title, textStyle: { color: '#8b949e', fontSize: 11, fontWeight: 'normal' }, left: 0, top: 0 }
        : undefined,
      grid: { left: 80, right: 60, top: title ? 30 : 10, bottom: 40 },
      tooltip: {
        backgroundColor: '#1c2128',
        borderColor: '#30363d',
        textStyle: { color: '#e6edf3', fontSize: 11 },
        formatter: (params: unknown) => {
          const p = params as { data: [number, number, number] };
          return `${xLabels[p.data[0]]} × ${yLabels[p.data[1]]}: ${p.data[2].toFixed(3)}`;
        },
      },
      xAxis: {
        type: 'category',
        data: xLabels,
        axisLine: { lineStyle: { color: '#30363d' } },
        axisLabel: { color: '#6e7681', fontSize: 10, rotate: 45 },
        splitArea: { show: true, areaStyle: { color: ['transparent', 'rgba(255,255,255,0.02)'] } },
      },
      yAxis: {
        type: 'category',
        data: yLabels,
        axisLine: { show: false },
        axisLabel: { color: '#e6edf3', fontSize: 10 },
      },
      visualMap: {
        min,
        max,
        calculable: true,
        orient: 'vertical',
        right: 0,
        top: 'center',
        inRange: {
          color: ['#f85149', '#21262d', '#3fb950'],
        },
        textStyle: { color: '#6e7681', fontSize: 10 },
      },
      series: [
        {
          type: 'heatmap',
          data: seriesData,
          label: {
            show: data.length <= 100,
            color: '#e6edf3',
            fontSize: 9,
            formatter: (params: unknown) => {
              const p = params as { data: [number, number, number] };
              return p.data[2].toFixed(2);
            },
          },
          emphasis: {
            itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0, 0, 0, 0.5)' },
          },
        },
      ],
    };
  }, [data, xLabels, yLabels, title]);

  return <BaseChart option={option} height={height} className={className} />;
}
