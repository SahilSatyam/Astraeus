'use client';

import { useRef, useEffect } from 'react';

export interface CandleData {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

interface PriceChartProps {
  data: CandleData[];
  height?: number;
  className?: string;
}

/**
 * Lightweight Charts (TradingView) — for price-only candle views.
 * Dynamic import to avoid bundle bloat. Uses v5 API.
 */
export function PriceChart({ data, height = 400, className = '' }: PriceChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<{ remove: () => void } | null>(null);

  useEffect(() => {
    let disposed = false;

    async function init() {
      if (!containerRef.current) return;

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const LWC = await import('lightweight-charts') as any;
      const { createChart, ColorType } = LWC;

      if (disposed) return;

      const chart = createChart(containerRef.current, {
        height,
        layout: {
          background: { type: ColorType.Solid, color: 'transparent' },
          textColor: '#8b949e',
          fontSize: 11,
        },
        grid: {
          vertLines: { color: '#21262d' },
          horzLines: { color: '#21262d' },
        },
        crosshair: {
          vertLine: { color: '#58a6ff', width: 1, style: 2 },
          horzLine: { color: '#58a6ff', width: 1, style: 2 },
        },
        timeScale: {
          borderColor: '#30363d',
          timeVisible: true,
        },
        rightPriceScale: {
          borderColor: '#30363d',
        },
      });

      const candleSeries = chart.addCandlestickSeries({
        upColor: '#3fb950',
        downColor: '#f85149',
        borderUpColor: '#3fb950',
        borderDownColor: '#f85149',
        wickUpColor: '#3fb950',
        wickDownColor: '#f85149',
      });

      candleSeries.setData(
        data.map((d) => ({
          time: d.time,
          open: d.open,
          high: d.high,
          low: d.low,
          close: d.close,
        })),
      );

      // Volume histogram if data has volume
      if (data.some((d) => d.volume !== undefined)) {
        const volumeSeries = chart.addHistogramSeries({
          priceFormat: { type: 'volume' },
          priceScaleId: 'volume',
        });

        chart.priceScale('volume').applyOptions({
          scaleMargins: { top: 0.8, bottom: 0 },
        });

        volumeSeries.setData(
          data
            .filter((d) => d.volume !== undefined)
            .map((d) => ({
              time: d.time,
              value: d.volume!,
              color: d.close >= d.open ? 'rgba(63, 185, 80, 0.3)' : 'rgba(248, 81, 73, 0.3)',
            })),
        );
      }

      chart.timeScale().fitContent();
      chartRef.current = chart;
    }

    init();

    return () => {
      disposed = true;
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
      }
    };
  }, [data, height]);

  return <div ref={containerRef} className={className} />;
}
