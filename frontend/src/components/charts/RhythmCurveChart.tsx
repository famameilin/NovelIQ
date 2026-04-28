/**
 * RhythmCurveChart - 节奏张力曲线图表组件
 *
 * 展示表层张力和综合张力曲线，支持三幕分界线和高潮标注
 *
 *   - 添加 dataZoom 支持，用于 Brush 缩放同步
 *   - 添加 chartRef 转发，支持外部访问 ECharts 实例
 *
 *   - 将 series 主色显式绑定到 CSS 变量
 *   - 统一图例、tooltip marker、折线颜色来源，避免与默认 ECharts 调色板错位
 *
 *   - 将展示层第一条节奏曲线切换为 surface_tension
 *   - 高潮标记改为绑定综合张力，避免语义与落点错位
 *
 *   - 当前端检测到表层张力仍是 0-1 而综合张力是 0-10 量级时，仅在显示层对前者做 x10 适配
 *   - 保持后端原始返回值不变，先验证产品显示效果
 */
import { useMemo, forwardRef } from "react";
import ReactEChartsCore from "echarts-for-react";
import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  MarkLineComponent,
  MarkPointComponent,
  DataZoomComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { getCSSColorVar } from "@/lib/theme";
import { cn } from "@/lib/cn";
import { useChartThemeSignature } from "@/hooks/useChartThemeSignature";
import type { ChunkCurvePoint, NarrativeStructureMetrics } from "@/api/types";

echarts.use([
  GridComponent,
  TooltipComponent,
  LegendComponent,
  MarkLineComponent,
  MarkPointComponent,
  DataZoomComponent,
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
  zoomRange?: [number, number] | null;
  onZoomChange?: (range: [number, number] | null) => void;
  height?: number | string;
}

const SERIES_CONFIG = [
  { key: "surface_tension", name: "表层张力", colorVar: "--chart-2" },
  { key: "tension_composite", name: "综合张力", colorVar: "--chart-3" },
] as const;

/* ------------------------------------------------------------------ */
/*  Component                                                         */
/* ------------------------------------------------------------------ */

export const RhythmCurveChart = forwardRef<ReactEChartsCore, RhythmCurveChartProps>(
  function RhythmCurveChart(
    {
      data,
      narrativeStructure,
      className,
      visibleSeries,
      onSeriesToggle,
      zoomRange,
      onZoomChange,
      height = 350,
    },
    ref
  ) {
    const themeSignature = useChartThemeSignature();
    const activeSeries = useMemo(
      () => visibleSeries ?? new Set(SERIES_CONFIG.map((s) => s.key)),
      [visibleSeries]
    );

    const borderColor = getCSSColorVar("--border");

    const option = useMemo(() => {
      if (!data.length) return {};

      const chart2Color = getCSSColorVar("--chart-2");
      const chart3Color = getCSSColorVar("--chart-3");

      const colorMap: Record<string, string> = {
        "--chart-2": chart2Color,
        "--chart-3": chart3Color,
      };

      const xData = data.map((d) => d.chunk_id);
      const totalChunks = xData.length;
      const compositeMax = Math.max(...data.map((d) => d.tension_composite ?? 0));
      const surfaceMax = Math.max(...data.map((d) => d.surface_tension ?? 0));
      const surfaceDisplayScale = surfaceMax <= 1.05 && compositeMax >= 2 ? 10 : 1;

      const act1Ratio = narrativeStructure?.act1_ratio ?? 0.25;
      const act2Ratio = narrativeStructure?.act2_ratio ?? 0.55;

      const act1End = Math.round(totalChunks * act1Ratio);
      const act2End = Math.round(totalChunks * (act1Ratio + act2Ratio));

      const climaxPositions = (narrativeStructure?.climax_positions ?? []).map(
        (ratio) => Math.round(totalChunks * ratio)
      );

      const series = SERIES_CONFIG.map((config) => {
        const color = colorMap[config.colorVar];
        // 老 run 的综合张力仍可能是 0-10 量级，而新的 surface_tension 目前是 0-1
        // 这里先只在前端显示层把表层张力按 x10 对齐，便于验证视觉效果，不改后端语义
        const values = data.map((d) => {
          const rawValue = d[config.key as keyof ChunkCurvePoint];
          if (typeof rawValue !== "number") return null;
          if (config.key === "surface_tension") {
            return rawValue * surfaceDisplayScale;
          }
          return rawValue;
        });
        const isActive = activeSeries.has(config.key);

        const markLineData: Array<{ xAxis: number; label?: object; lineStyle?: object }> = [];

        if (isActive) {
          if (act1End > 0 && act1End < totalChunks) {
            markLineData.push({
              xAxis: act1End,
              label: { show: true, formatter: "第一幕", position: "start", color: "hsl(var(--text-muted))", fontSize: 10 },
              lineStyle: { type: "dashed", color: borderColor, opacity: 0.6 },
            });
          }
          if (act2End > 0 && act2End < totalChunks) {
            markLineData.push({
              xAxis: act2End,
              label: { show: true, formatter: "第二幕", position: "start", color: "hsl(var(--text-muted))", fontSize: 10 },
              lineStyle: { type: "dashed", color: borderColor, opacity: 0.6 },
            });
          }
        }

        return {
          name: config.name,
          type: "line" as const,
          color,
          data: isActive ? values : [],
          smooth: true,
          showSymbol: false,
          itemStyle: { color },
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

      const climaxMarkPoint = climaxPositions.length > 0 ? {
        data: climaxPositions.map((chunkIdx) => ({
          coord: [chunkIdx, Math.max(...data.map((d) => d.tension_composite ?? 0))],
          value: "高潮",
          itemStyle: { color: chart3Color },
          symbolSize: 40,
          label: { show: true, fontSize: 9, color: "#fff" },
        })),
      } : undefined;

      const baseOption = {
        grid: {
          top: 60,
          right: 30,
          bottom: 60,
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
        dataZoom: [
          {
            type: "inside" as const,
            xAxisIndex: 0,
            start: zoomRange ? (zoomRange[0] / totalChunks) * 100 : 0,
            end: zoomRange ? (zoomRange[1] / totalChunks) * 100 : 100,
          },
          {
            type: "slider" as const,
            xAxisIndex: 0,
            start: zoomRange ? (zoomRange[0] / totalChunks) * 100 : 0,
            end: zoomRange ? (zoomRange[1] / totalChunks) * 100 : 100,
            height: 20,
            bottom: 10,
            borderColor: borderColor,
            backgroundColor: "hsl(var(--surface))",
            fillerColor: "hsl(var(--primary) / 0.1)",
            handleStyle: { color: "hsl(var(--primary))" },
            textStyle: { color: "hsl(var(--text-muted))", fontSize: 10 },
          },
        ],
        xAxis: {
          type: "category" as const,
          data: xData,
          name: "分块",
          nameLocation: "middle",
          nameGap: 25,
          nameTextStyle: { color: "hsl(var(--text-muted))", fontSize: 12 },
          axisLine: { lineStyle: { color: borderColor } },
          axisTick: { lineStyle: { color: borderColor } },
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
          splitLine: { lineStyle: { color: borderColor, opacity: 0.5 } },
          axisLabel: { color: "hsl(var(--text-muted))", fontSize: 11 },
        },
        series: series.map((s, idx) => ({
          ...s,
          markPoint: SERIES_CONFIG[idx]?.key === "tension_composite" && climaxMarkPoint ? climaxMarkPoint : undefined,
        })),
      };

      return baseOption;
    }, [data, narrativeStructure, activeSeries, onSeriesToggle, zoomRange, borderColor]);

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

    const handleDataZoom = (params: { batch?: Array<{ start: number; end: number }> }) => {
      if (!onZoomChange || !data.length) return;

      if (params.batch && params.batch.length > 0) {
        const { start, end } = params.batch[0];
        const startIdx = Math.round((start / 100) * data.length);
        const endIdx = Math.round((end / 100) * data.length);
        onZoomChange([startIdx, endIdx]);
      } else {
        onZoomChange(null);
      }
    };

    return (
      <div className={cn("relative", className)}>
        <ReactEChartsCore
          key={themeSignature}
          ref={ref}
          echarts={echarts}
          option={option}
          style={{ height: typeof height === "number" ? `${height}px` : height, width: "100%" }}
          notMerge
          lazyUpdate
          onEvents={{
            legendClick: handleLegendClick,
            datazoom: handleDataZoom,
          }}
        />
      </div>
    );
  }
);
