import { useMemo } from "react";
import ReactEChartsCore from "echarts-for-react";
import * as echarts from "echarts/core";
import { LineChart, MarkPointComponent } from "echarts/charts";
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  MarkLineComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { getCSSColorVar } from "@/lib/theme";
import { cn } from "@/lib/cn";
import type { ChunkCurvePoint, NarrativeStructureMetrics } from "@/api/types";

echarts.use([
  GridComponent,
  TooltipComponent,
  LegendComponent,
  MarkLineComponent,
  MarkPointComponent,
  LineChart,
  CanvasRenderer,
]);

/* ------------------------------------------------------------------ */
/*  Types                                                             */
/* ------------------------------------------------------------------ */

export interface RhythmCurveChartProps {
  data: ChunkCurvePoint[];
  narrativeStructure?: NarrativeStructureMetrics;
  className?: string;
  visibleSeries?: Set<string>;
  onSeriesToggle?: (series: Set<string>) => void;
}

const SERIES_CONFIG = [
  { key: "tension_proxy", name: "张力代理", colorVar: "--chart-2" },
  { key: "tension_composite", name: "综合张力", colorVar: "--chart-3" },
] as const;

/* ------------------------------------------------------------------ */
/*  Component                                                         */
/* ------------------------------------------------------------------ */

export function RhythmCurveChart({
  data,
  narrativeStructure,
  className,
  visibleSeries,
  onSeriesToggle,
}: RhythmCurveChartProps) {
  // Default: both series visible
  const activeSeries = visibleSeries ?? new Set(SERIES_CONFIG.map((s) => s.key));

  const chart2Color = getCSSColorVar("--chart-2");
  const chart3Color = getCSSColorVar("--chart-3");

  const colorMap: Record<string, string> = {
    "--chart-2": chart2Color,
    "--chart-3": chart3Color,
  };

  const option = useMemo(() => {
    if (!data.length) return {};

    const xData = data.map((d) => d.chunk_id);
    const totalChunks = xData.length;

    // Calculate three-act division lines
    const act1Ratio = narrativeStructure?.act1_ratio ?? 0.25;
    const act2Ratio = narrativeStructure?.act2_ratio ?? 0.55;
    const act3Ratio = narrativeStructure?.act3_ratio ?? 0.20;

    const act1End = Math.round(totalChunks * act1Ratio);
    const act2End = Math.round(totalChunks * (act1Ratio + act2Ratio));

    // Get climax positions (convert from ratios to chunk indices)
    const climaxPositions = (narrativeStructure?.climax_positions ?? []).map(
      (ratio) => Math.round(totalChunks * ratio)
    );

    const series = SERIES_CONFIG.map((config) => {
      const color = colorMap[config.colorVar];
      const values = data.map((d) => d[config.key as keyof ChunkCurvePoint] ?? null);
      const isActive = activeSeries.has(config.key);

      // Build markLine for three-act division
      const markLineData: echarts.MarkLineComponentDataItem[] = [];

      if (config.key === "tension_proxy" || config.key === "tension_composite") {
        if (act1End > 0 && act1End < totalChunks) {
          markLineData.push({
            xAxis: act1End,
            label: { show: true, formatter: "第一幕", position: "start", color: "hsl(var(--text-muted))", fontSize: 10 },
            lineStyle: { type: "dashed", color: "hsl(var(--border))", opacity: 0.6 },
          });
        }
        if (act2End > 0 && act2End < totalChunks) {
          markLineData.push({
            xAxis: act2End,
            label: { show: true, formatter: "第二幕", position: "start", color: "hsl(var(--text-muted))", fontSize: 10 },
            lineStyle: { type: "dashed", color: "hsl(var(--border))", opacity: 0.6 },
          });
        }
      }

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
        markLine: markLineData.length > 0 ? {
          symbol: "none",
          data: markLineData,
          animation: false,
        } : undefined,
        animationDuration: 800,
      };
    });

    // Add climax markers
    const climaxMarkPoint = climaxPositions.length > 0 ? {
      data: climaxPositions.map((chunkIdx) => ({
        coord: [chunkIdx, Math.max(...data.map((d) => d.tension_proxy ?? 0))],
        value: "高潮",
        itemStyle: { color: chart3Color },
        symbolSize: 40,
        label: { show: true, fontSize: 9, color: "#fff" },
      })),
    } : undefined;

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
          const activeParams = params.filter((p) => p.value !== undefined && p.value !== null);
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
        name: "张力",
        nameTextStyle: { color: "hsl(var(--text-muted))", fontSize: 12 },
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: { lineStyle: { color: "hsl(var(--border))", opacity: 0.5 } },
        axisLabel: { color: "hsl(var(--text-muted))", fontSize: 11 },
      },
      series: series.map((s, idx) => ({
        ...s,
        markPoint: idx === 0 && climaxMarkPoint ? climaxMarkPoint : undefined,
      })),
    };
  }, [data, narrativeStructure, activeSeries, onSeriesToggle, chart2Color, chart3Color]);

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