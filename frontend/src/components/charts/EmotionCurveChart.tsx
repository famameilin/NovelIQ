/**
 * EmotionCurveChart - 情绪趋势曲线图表组件
 * 
 * 创建时间: 2026-04-04
 * 创建者: AI Assistant
 * 任务: Phase 1-D 情绪/节奏曲线
 * 说明: 展示基于词表命中的正面/负面/净/平滑密度四条曲线，支持系列切换和缩放同步
 * 
 * 修改时间: 2026-04-04
 * 修改者: AI Assistant
 * 修改内容: 
 *   - 添加 dataZoom 支持，用于 Brush 缩放同步
 *   - 添加 chartRef 转发，支持外部访问 ECharts 实例
 *
 * 修改时间: 2026-04-21
 * 修改者: Codex
 * 任务: 修复情绪趋势曲线图例颜色错位
 * 修改内容:
 *   - 将 series 主色显式绑定到 CSS 变量
 *   - 统一图例、tooltip marker、折线颜色来源，避免与默认 ECharts 调色板错位
 *   - 删除未使用的 hslToHsla 导入
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
  DataZoomComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { getCSSColorVar } from "@/lib/theme";
import { cn } from "@/lib/cn";
import type { ChunkCurvePoint } from "@/api/types";

echarts.use([
  GridComponent,
  TooltipComponent,
  LegendComponent,
  MarkLineComponent,
  DataZoomComponent,
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
  zoomRange?: [number, number] | null;
  onZoomChange?: (range: [number, number] | null) => void;
  height?: number | string;
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

export const EmotionCurveChart = forwardRef<ReactEChartsCore, EmotionCurveChartProps>(
  function EmotionCurveChart(
    {
      data,
      className,
      visibleSeries,
      onSeriesToggle,
      zoomRange,
      onZoomChange,
      height = 350,
    },
    ref
  ) {
    const activeSeries = useMemo(
      () => visibleSeries ?? new Set(SERIES_CONFIG.map((s) => s.key)),
      [visibleSeries]
    );

    const borderColor = getCSSColorVar("--border");

    const option = useMemo(() => {
      if (!data.length) return {};

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

      const xData = data.map((d) => d.chunk_id);
      const totalChunks = xData.length;

      const series = SERIES_CONFIG.map((config) => {
        const color = colorMap[config.colorVar];
    // 中文注释：情绪趋势曲线允许后端返回 null 表示缺值，这里保留空洞，
        // 避免把“没算出来”和“真实为 0”混成同一条贴地折线。
        const values = data.map((d) => d[config.key as keyof ChunkCurvePoint] ?? null);
        const isActive = activeSeries.has(config.key);

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
          animationDuration: 800,
        };
      });

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
          formatter: (params: Array<{ seriesName: string; value: number | null; marker: string; axisValue?: string }>) => {
            if (!Array.isArray(params) || params.length === 0) return "";
            const chunkId = params[0]?.axisValue ?? "";
            let html = `<div class="font-medium mb-1">分块 ${chunkId}</div>`;
            const activeParams = params.filter((p) => p.value !== undefined && p.value !== null);
            html += activeParams
              .map((p) => `<div class="flex items-center gap-1">${p.marker} ${p.seriesName}: <span class="font-mono">${typeof p.value === "number" ? p.value.toFixed(4) : "-"}</span></div>`)
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
          name: "密度",
          nameTextStyle: { color: "hsl(var(--text-muted))", fontSize: 12 },
          axisLine: { show: false },
          axisTick: { show: false },
          splitLine: { lineStyle: { color: borderColor, opacity: 0.5 } },
          axisLabel: { color: "hsl(var(--text-muted))", fontSize: 11 },
        },
        series,
      };

      return baseOption;
    }, [data, activeSeries, onSeriesToggle, zoomRange, borderColor]);

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
