/**
 * RhythmCurveChart - 节奏张力曲线图表组件
 *
 * 展示表层张力和平滑张力曲线，支持三幕分界线和高潮标注
 *
 *   - 添加 dataZoom 支持，用于 Brush 缩放同步
 *   - 添加 chartRef 转发，支持外部访问 ECharts 实例
 *
 *   - 将 series 主色显式绑定到 CSS 变量
 *   - 统一图例、tooltip marker、折线颜色来源，避免与默认 ECharts 调色板错位
 *
 *   - 将展示层第一条节奏曲线切换为 surface_tension
 *   - 高潮标记改为绑定平滑张力，避免语义与落点错位
 *
 *   - 当前端检测到表层张力仍是 0-1 而综合张力是 0-10 量级时，仅在显示层对前者做 x10 适配
 *   - 保持后端原始返回值不变，先验证产品显示效果
 *
 *   - M4 段落粒度改造：数据源从 ChunkCurvePoint 换为 ParagraphCurvePoint
 *   - x 轴从分块序号改为连续数值 position（值域 [0,1]），三幕 markLine 与高潮
 *     markPoint 直接用 0-1 比例坐标（act1_ratio / climax_positions 与 position 同域）
 *   - tooltip 改为章节/段落实名，dataZoom 换算改为 position 值域占比
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
import type { ParagraphCurvePoint, NarrativeStructureMetrics } from "@/api/types";

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
/*  类型定义                                                           */
/* ------------------------------------------------------------------ */

export interface RhythmCurveChartProps {
  data: ParagraphCurvePoint[];
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
  { key: "smoothed_surface_tension", name: "平滑张力", colorVar: "--chart-3" },
] as const;

/* ------------------------------------------------------------------ */
/*  组件主体                                                           */
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

      const compositeValues = data
        .map((point) => point.smoothed_surface_tension)
        .filter((value): value is number => value != null && Number.isFinite(value));
      const surfaceValues = data
        .map((point) => point.surface_tension)
        .filter((value): value is number => value != null && Number.isFinite(value));
      const compositeMax = compositeValues.length > 0 ? Math.max(...compositeValues) : 0;
      const surfaceMax = surfaceValues.length > 0 ? Math.max(...surfaceValues) : 0;
      const surfaceDisplayScale = surfaceMax <= 1.05 && compositeMax >= 2 ? 10 : 1;

      // 三幕分界：缺样本时不画假的 25/55 分割线
      const act1Ratio = narrativeStructure?.act1_ratio;
      const act2Ratio = narrativeStructure?.act2_ratio;
      const act1End =
        act1Ratio != null && act1Ratio > 0 && act1Ratio < 1 ? act1Ratio : null;
      const act2End =
        act1Ratio != null && act2Ratio != null
          ? Math.min(act1Ratio + act2Ratio, 1)
          : null;

      // climax_positions：归一化进度 [0,1]
      const climaxPositions =
        narrativeStructure?.climax_positions?.filter(
          (position): position is number => Number.isFinite(position),
        ) ?? [];
      const tensionValues = data
        .map((point) => point.smoothed_surface_tension)
        .filter((value): value is number => value != null && Number.isFinite(value));
      const tensionPeak = tensionValues.length > 0 ? Math.max(...tensionValues) : null;

      const series = SERIES_CONFIG.map((config) => {
        const color = colorMap[config.colorVar];
        // 老 run 的综合张力仍可能是 0-10 量级，而新的 surface_tension 目前是 0-1
        // 这里先只在前端显示层把表层张力按 x10 对齐，便于验证视觉效果，不改后端语义
        const values = data.map((d) => {
          const rawValue = d[config.key as keyof ParagraphCurvePoint];
          if (typeof rawValue !== "number") return [d.position, null] as [number, null];
          if (config.key === "surface_tension") {
            return [d.position, rawValue * surfaceDisplayScale] as [number, number];
          }
          return [d.position, rawValue] as [number, number];
        });
        const isActive = activeSeries.has(config.key);

        const markLineData: Array<{ xAxis: number; label?: object; lineStyle?: object }> = [];

        if (isActive) {
          if (act1End != null && act1End > 0 && act1End < 1) {
            markLineData.push({
              xAxis: act1End,
              label: { show: true, formatter: "第一幕", position: "start", color: "hsl(var(--text-muted))", fontSize: 10 },
              lineStyle: { type: "dashed", color: borderColor, opacity: 0.6 },
            });
          }
          if (act2End != null && act2End > 0 && act2End < 1) {
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
            // 轴向 tooltip 已提供对比反馈，禁用 emphasis 避免悬浮时隐藏曲线
            disabled: true,
          },
          markLine: markLineData.length > 0 ? {
            symbol: "none",
            data: markLineData,
            animation: false,
          } : undefined,
          animationDuration: 800,
        };
      });

      const climaxMarkPoint = climaxPositions.length > 0 && tensionPeak != null ? {
        data: climaxPositions.map((ratio) => ({
          coord: [ratio, tensionPeak],
          value: `高潮 ${(ratio * 100).toFixed(0)}%`,
          itemStyle: { color: chart3Color },
          symbolSize: 40,
          label: { show: true, formatter: "{c}", fontSize: 9, color: "#fff" },
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
          formatter: (
            params: Array<{
              seriesName: string;
              value: number | [number, number | null] | null;
              marker: string;
              dataIndex?: number;
            }>
          ) => {
            if (!Array.isArray(params) || params.length === 0) return "";
            const point = data[params[0]?.dataIndex ?? -1];
            if (!point) return "";
            let html = `<div class="font-medium mb-1">第 ${point.chapter_id} 章 第 ${point.paragraph_index + 1} 段 · 全书进度 ${(point.position * 100).toFixed(1)}%</div>`;
            const activeParams = params.filter((p) => p.value !== undefined && p.value !== null);
            html += activeParams
              .map((p) => {
                // 数值轴的折线点使用 [x, y] 形式传给 tooltip，需要取第二项作为展示值
                const value = Array.isArray(p.value) ? p.value[1] : p.value;
                const formattedValue = typeof value === "number" ? value.toFixed(4) : "-";
                return `<div class="flex items-center gap-1">${p.marker} ${p.seriesName}: <span class="font-mono">${formattedValue}</span></div>`;
              })
              .join("");
            return html;
          },
        },
        dataZoom: [
          {
            type: "inside" as const,
            xAxisIndex: 0,
            start: zoomRange ? zoomRange[0] * 100 : 0,
            end: zoomRange ? zoomRange[1] * 100 : 100,
          },
          {
            type: "slider" as const,
            xAxisIndex: 0,
            start: zoomRange ? zoomRange[0] * 100 : 0,
            end: zoomRange ? zoomRange[1] * 100 : 100,
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
          type: "value" as const,
          min: 0,
          max: 1,
          name: "全书进度",
          nameLocation: "middle",
          nameGap: 25,
          nameTextStyle: { color: "hsl(var(--text-muted))", fontSize: 12 },
          axisLine: { lineStyle: { color: borderColor } },
          axisTick: { lineStyle: { color: borderColor } },
          axisLabel: {
            color: "hsl(var(--text-muted))",
            fontSize: 11,
            formatter: (value: number) => `${(value * 100).toFixed(0)}%`,
          },
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
          markPoint: SERIES_CONFIG[idx]?.key === "smoothed_surface_tension" && climaxMarkPoint ? climaxMarkPoint : undefined,
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
        // position 值域为 [0,1]，百分比直接除以 100 得到 position 数值对
        const startPos = start / 100;
        const endPos = end / 100;
        onZoomChange([startPos, endPos]);
      } else {
        onZoomChange(null);
      }
    };

    return (
      <div className={cn("relative", className)}>
        {(narrativeStructure?.act1_ratio != null ||
          narrativeStructure?.act2_ratio != null ||
          narrativeStructure?.act3_ratio != null) && (
          <span className="pointer-events-none absolute left-3 top-2 z-10 rounded-full border border-border/70 bg-surface/85 px-2 py-1 text-[10px] text-text-muted">
            三幕：全书进度
          </span>
        )}
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
