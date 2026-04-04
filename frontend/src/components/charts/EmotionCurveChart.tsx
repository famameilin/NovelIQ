import { useMemo } from "react";
import ReactEChartsCore from "echarts-for-react";
import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  MarkLineComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { getCSSColorVar, hslToHsla } from "@/lib/theme";
import { cn } from "@/lib/cn";
import type { ChunkCurvePoint } from "@/api/types";

echarts.use([
  GridComponent,
  TooltipComponent,
  LegendComponent,
  MarkLineComponent,
  LineChart,
  CanvasRenderer,
]);

/* ------------------------------------------------------------------ */
/*  Types                                                             */
/* ------------------------------------------------------------------ */

export interface EmotionCurveChartProps {
  data: ChunkCurvePoint[];
  className?: string;
  visibleSeries?: Set<string>;
  onSeriesToggle?: (series: Set<string>) => void;
}

const SERIES_CONFIG = [
  { key: "pos_density", name: "正面密度", colorVar: "--chart-positive" },
  { key: "neg_density", name: "负面密度", colorVar: "--chart-negative" },
  { key: "net_density", name: "净密度", colorVar: "--chart-1" },
  { key: "smoothed_density", name: "平滑密度", colorVar: "--primary" },
] as const;

/* ------------------------------------------------------------------ */
/*  Component                                                         */
/* ------------------------------------------------------------------ */

export function EmotionCurveChart({
  data,
  className,
  visibleSeries,
  onSeriesToggle,
}: EmotionCurveChartProps) {
  // Default: all series visible
  const activeSeries = visibleSeries ?? new Set(SERIES_CONFIG.map((s) => s.key));

  const positiveColor = getCSSColorVar("--chart-positive");
  const negativeColor = getCSSColorVar("--chart-negative");
  const neutralColor = getCSSColorVar("--chart-1");
  const primaryColor = getCSSColorVar("--primary");

  const colorMap: Record<string, string> = {
    "--chart-positive": positiveColor,
    "--chart-negative": negativeColor,
    "--chart-1": neutralColor,
    "--primary": primaryColor,
  };

  const option = useMemo(() => {
    if (!data.length) return {};

    const xData = data.map((d) => d.chunk_id);

    const series = SERIES_CONFIG.map((config) => {
      const color = colorMap[config.colorVar];
      const values = data.map((d) => d[config.key as keyof ChunkCurvePoint] ?? 0);
      const isActive = activeSeries.has(config.key);

      return {
        name: config.name,
        type: "line" as const,
        data: isActive ? values : [],
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 2, color },
        emphasis: {
          focus: "series" as const,
        },
        animationDuration: 800,
      };
    });

    return {
      grid: {
        top: 60,
        right: 30,
        bottom: 40,
        left: 50,
        containLabel: false,
      },
      legend: {
        show: !!onSeriesToggle,
        top: 8,
        itemGap: 20,
        textStyle: { color: "hsl(var(--text-muted))", fontSize: 12 },
        icon: "roundRect",
        data: SERIES_CONFIG.map((s) => s.name),
      },
      tooltip: {
        trigger: "axis" as const,
        axisPointer: { type: "cross" as const, crossStyle: { color: "#999" } },
        backgroundColor: "hsl(var(--surface))",
        borderColor: "hsl(var(--border))",
        textStyle: { color: "hsl(var(--text))", fontSize: 12 },
        formatter: (params: Array<{ seriesName: string; value: number; marker: string; axisValue?: string }>) => {
          if (!Array.isArray(params) || params.length === 0) return "";
          const chunkId = params[0]?.axisValue ?? "";
          let html = `<div class="font-medium mb-1">分块 ${chunkId}</div>`;
          const activeParams = params.filter((p) => p.value !== undefined && p.value !== 0);
          html += activeParams
            .map((p) => `<div class="flex items-center gap-1">${p.marker} ${p.seriesName}: <span class="font-mono">${p.value?.toFixed(4) ?? "-"}</span></div>`)
            .join("");
          return html;
        },
      },
      xAxis: {
        type: "category" as const,
        data: xData,
        name: "分块",
        nameLocation: "middle",
        nameGap: 25,
        nameTextStyle: { color: "hsl(var(--text-muted))", fontSize: 12 },
        axisLine: { lineStyle: { color: "hsl(var(--border))" } },
        axisTick: { lineStyle: { color: "hsl(var(--border))" } },
        axisLabel: {
          color: "hsl(var(--text-muted))",
          fontSize: 11,
          interval: Math.floor(xData.length / 10),
        },
        boundaryGap: false,
      },
      yAxis: {
        type: "value" as const,
        name: "密度",
        nameTextStyle: { color: "hsl(var(--text-muted))", fontSize: 12 },
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: { lineStyle: { color: "hsl(var(--border))", opacity: 0.5 } },
        axisLabel: { color: "hsl(var(--text-muted))", fontSize: 11 },
      },
      series,
    };
  }, [data, activeSeries, onSeriesToggle]);

  const handleLegendClick = (event: { name: string }) => {
    if (!onSeriesToggle) return;

    const clickedKey = SERIES_CONFIG.find((s) => s.name === event.name)?.key;
    if (!clickedKey) return;

    const newSet = new Set(activeSeries);
    if (newSet.has(clickedKey)) {
      newSet.delete(clickedKey);
    } else {
      newSet.add(clickedKey);
    }
    onSeriesToggle(newSet);
  };

  return (
    <div className={cn("relative", className)}>
      <ReactEChartsCore
        echarts={echarts}
        option={option}
        style={{ height: "100%", width: "100%" }}
        notMerge
        lazyUpdate
        onEvents={{ legendClick: handleLegendClick }}
      />
    </div>
  );
}