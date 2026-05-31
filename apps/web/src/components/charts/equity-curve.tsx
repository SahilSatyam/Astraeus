'use client';

import { useMemo } from 'react';
import type { EChartsOption } from 'echarts';
import { BaseChart } from './base-chart';

export interface EquityCurvePoint {
  date: string;
  value: number;
  drawdown?: number;
}

interface EquityCurveProps {
  data: EquityCurvePoint[];
  benchmark?: EquityCurvePoint[];
  height?: string | number;
  showDrawdown?: boolean;
  className?: string;
}

/**
 * Equity curve chart — primary backtest visualization.
 * Optionally shows drawdown as a secondary axis area chart.
 */
export function EquityCurve({
  data,
  benchmark,
  height = 300,
  showDrawdown = true,
  className = '',
}: EquityCurveProps) {
  const option = useMemo<EChartsOption>(() => {
    const dates = data.map((d) => d.date);
    const values = data.map((d) => d.value);
    const drawdowns = data.map((d) => d.drawdown ?? 0);

    const series: EChartsOption['series'] = [
      {
        name: 'Portfolio',
        type: 'line',
        data: values,
        smooth: false,
        lineStyle: { width: 1.5, color: '#58a6ff' },
        itemStyle: { color: '#58a6ff' },
        showSymbol: false,
        yAxisIndex: 0,
      },
    ];

    if (benchmark) {
      series.push({
        name: 'Benchmark',
        type: 'line',
        data: benchmark.map((d) => d.value),
        smooth: false,
        lineStyle: { width: 1, color: '#6e7681', type: 'dashed' },
        itemStyle: { color: '#6e7681' },
        showSymbol: false,
        yAxisIndex: 0,
      });
    }

    if (showDrawdown) {
      series.push({
        name: 'Drawdown',
        type: 'line',
        data: drawdowns,
        smooth: false,
        lineStyle: { width: 1, color: '#f85149' },
        areaStyle: { color: 'rgba(248, 81, 73, 0.15)' },
        itemStyle: { color: '#f85149' },
        showSymbol: false,
        yAxisIndex: 1,
      });
    }

    return {
      backgroundColor: 'transparent',
      grid: { left: 60, right: 60, top: 30, bottom: 30 },
      tooltip: {
        trigger: 'axis',
        backgroundColor: '#1c2128',
        borderColor: '#30363d',
        textStyle: { color: '#e6edf3', fontSize: 11 },
      },
      legend: {
        top: 0,
        textStyle: { color: '#8b949e', fontSize: 11 },
      },
      xAxis: {
        type: 'category',
        data: dates,
        axisLine: { lineStyle: { color: '#30363d' } },
        axisLabel: { color: '#6e7681', fontSize: 10 },
        splitLine: { show: false },
      },
      yAxis: [
        {
          type: 'value',
          axisLine: { show: false },
          axisLabel: { color: '#6e7681', fontSize: 10 },
          splitLine: { lineStyle: { color: '#21262d' } },
        },
        ...(showDrawdown
          ? [
              {
                type: 'value' as const,
                position: 'right' as const,
                axisLine: { show: false },
                axisLabel: {
                  color: '#6e7681',
                  fontSize: 10,
                  formatter: (v: number) => `${(v * 100).toFixed(0)}%`,
                },
                splitLine: { show: false },
                max: 0,
              },
            ]
          : []),
      ],
      series,
    };
  }, [data, benchmark, showDrawdown]);

  return <BaseChart option={option} height={height} className={className} />;
}
