/**
 * EmotionTrendChart - 情绪趋势窗口聚合图表组件
 *
 * 展示窗口聚合的正负情绪强度、原始趋势与后端平滑趋势，
 * 保持旧版情绪曲线的折线视觉语义并支持缩放自适应重聚合。
 *
 *   - x 轴为连续 position（值域 [0,1]），dataZoom 区间即聚合作用域
 *   - 平滑由后端请求链路完成，前端只绘制返回值，不重复计算
 *   - 覆盖率字段仍由接口返回用于窗口统计合同，但不作为图表系列展示
 */
import { useMemo, forwardRef } from "react";
import ReactEChartsCore from "echarts-for-react";
import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DataZoomComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { getCSSColorVar, hslToHsla } from "@/lib/theme";
import { cn } from "@/lib/cn";
import { useChartThemeSignature } from "@/hooks/useChartThemeSignature";
import type { EmotionTrendWindow } from "@/api/types";
import {
  EMOTION_TREND_SERIES_CONFIG,
  formatEmotionTrendTooltipValue,
  getEmotionTrendSeriesValue,
} from "./emotionTrendSeries";

export type { EmotionTrendSeriesKey } from "./emotionTrendSeries";

echarts.use([
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DataZoomComponent,
  LineChart,
  CanvasRenderer,
]);

/* ------------------------------------------------------------------ */
/*  类型定义                                                           */
/* ------------------------------------------------------------------ */

export interface EmotionTrendChartProps {
  data: EmotionTrendWindow[];
  className?: string;
  visibleSeries?: Set<string>;
  onSeriesToggle?: (series: Set<string>) => void;
  zoomRange?: [number, number] | null;
  onZoomChange?: (range: [number, number] | null) => void;
  onZoomEnd?: (range: [number, number] | null) => void;
  onPointClick?: (window: EmotionTrendWindow) => void;
  height?: number | string;
}

interface ChartClickParams {
  dataIndex?: number;
}

/* ------------------------------------------------------------------ */
/*  组件主体                                                           */
/* ------------------------------------------------------------------ */

export const EmotionTrendChart = forwardRef<ReactEChartsCore, EmotionTrendChartProps>(
  function EmotionTrendChart(
    {
      data,
      className,
      visibleSeries,
      onSeriesToggle,
      zoomRange,
      onZoomChange,
      onZoomEnd,
      onPointClick,
      height = 350,
    },
    ref
  ) {
    const themeSignature = useChartThemeSignature();
    const activeSeries = useMemo(
      () => visibleSeries ?? new Set(EMOTION_TREND_SERIES_CONFIG.map((s) => s.key)),
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

      // 窗口 x 坐标取窗内中点，所有曲线共用连续的 position 轴
      const centers = data.map(
        (w) => w.position ?? (w.start_position + w.end_position) / 2
      );

      const series = EMOTION_TREND_SERIES_CONFIG.map((config) => {
        const color = colorMap[config.colorVar];
        const isActive = activeSeries.has(config.key);
        const isMainSeries = config.role === "main";
        const isSupportSeries = config.role === "support";
        const lineOpacity = isMainSeries ? 1 : isSupportSeries ? 0.55 : 0.38;
        const lineWidth = isMainSeries ? 3 : isSupportSeries ? 2 : 1.5;
        const lineType = isSupportSeries ? "dashed" : "solid";
        const values = centers.map((center, index) => {
          const window = data[index];
          const value = getEmotionTrendSeriesValue(window, config);
          return value != null ? [center, value] : [center, null];
        });

        return {
          name: config.name,
          type: "line" as const,
          color,
          data: isActive ? values : [],
          // 后端负责数值平滑，这里只开启 ECharts 的曲线渲染，避免折线出现棱角
          smooth: true,
          showSymbol: false,
          z: isMainSeries ? 4 : isSupportSeries ? 3 : 2,
          itemStyle: { color, opacity: lineOpacity },
          lineStyle: {
            width: lineWidth,
            color: hslToHsla(color, lineOpacity),
            type: lineType,
          },
          areaStyle: isMainSeries
            ? {
                color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                  { offset: 0, color: hslToHsla(color, 0.12) },
                  { offset: 1, color: hslToHsla(color, 0.01) },
                ]),
              }
            : undefined,
          // 轴向 tooltip 已提供对比反馈，禁用 emphasis 避免悬浮时淡化曲线
          emphasis: { disabled: true },
          animationDuration: 800,
        };
      });

      // 右轴按当前窗口密度自适应，保留零线并给极小量级留出可读边距
      const densityValues = series.flatMap((item) =>
        (item.data as Array<[number, number | null]>).flatMap(([, value]) =>
          typeof value === "number" && Number.isFinite(value) ? [value] : []
        )
      );
      const densityMin = densityValues.length > 0 ? Math.min(0, ...densityValues) : undefined;
      const densityMax = densityValues.length > 0 ? Math.max(0, ...densityValues) : undefined;
      const densitySpan =
        densityMin != null && densityMax != null
          ? Math.max(densityMax - densityMin, 0.001)
          : undefined;
      const densityPadding = densitySpan != null ? densitySpan * 0.15 : undefined;

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
          data: EMOTION_TREND_SERIES_CONFIG.map((s) => s.name),
        },
        tooltip: {
          trigger: "axis" as const,
          axisPointer: { type: "cross" as const, crossStyle: { color: "#999" } },
          backgroundColor: "hsl(var(--surface))",
          borderColor: "hsl(var(--border))",
          textStyle: { color: "hsl(var(--text))", fontSize: 12 },
          formatter: (params: Array<{ seriesName: string; value: unknown; marker: string; dataIndex?: number }>) => {
            if (!Array.isArray(params) || params.length === 0) return "";
            const windowIndex = Number(params[0]?.dataIndex ?? -1);
            const window = data[windowIndex];
            if (!window) return "";
            const chapterLabel =
              window.chapter_start === window.chapter_end
                ? `第 ${window.chapter_start} 章`
                : `第 ${window.chapter_start}~${window.chapter_end} 章`;
            let html = `<div class="font-medium mb-1">情绪窗口聚合 · ${chapterLabel} · 第 ${window.paragraph_start + 1}~${window.paragraph_end + 1} 段（共 ${window.paragraph_total} 段）</div>`;
            const activeParams = params.filter((p) => p.value !== undefined && p.value !== null);
            html += activeParams
              .map(
                (p) =>
                    `<div class="flex items-center gap-1">${p.marker} ${p.seriesName}: <span class="font-mono">${formatEmotionTrendTooltipValue(p.value)}</span></div>`
              )
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
          name: "章节进度",
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
          name: "情绪密度",
          min: densityMin != null && densityPadding != null ? densityMin - densityPadding : undefined,
          max: densityMax != null && densityPadding != null ? densityMax + densityPadding : undefined,
          nameTextStyle: { color: "hsl(var(--text-muted))", fontSize: 12 },
          axisLine: { show: false },
          axisTick: { show: false },
          splitLine: { lineStyle: { color: borderColor, opacity: 0.5 } },
          axisLabel: {
            color: "hsl(var(--text-muted))",
            fontSize: 11,
            formatter: (value: number) => value.toFixed(4),
          },
        },
        series,
      };

      return baseOption;
    }, [data, activeSeries, onSeriesToggle, zoomRange, borderColor]);

    const handleLegendClick = (event: { name: string }) => {
      if (!onSeriesToggle) return;

      const clickedKey = EMOTION_TREND_SERIES_CONFIG.find((s) => s.name === event.name)?.key;
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
        const range: [number, number] = [start / 100, end / 100];
        onZoomChange(range);
        // ECharts 版本未提供 datazoomend 时，以 datazoom 的最后一次事件作为防抖兜底
        onZoomEnd?.(range);
      } else {
        onZoomChange(null);
        onZoomEnd?.(null);
      }
    };

    const handleDataZoomEnd = (params: { batch?: Array<{ start: number; end: number }> }) => {
      if (!onZoomEnd || !data.length) return;
      if (params.batch && params.batch.length > 0) {
        const { start, end } = params.batch[0];
        onZoomEnd([start / 100, end / 100]);
      } else {
        onZoomEnd(null);
      }
    };

    const handleChartClick = (params: ChartClickParams) => {
      if (!onPointClick) return;
      if (typeof params?.dataIndex !== "number") return;
      const window = data[params.dataIndex];
      if (!window) return;
      onPointClick(window);
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
            datazoomend: handleDataZoomEnd,
            click: handleChartClick,
          }}
        />
      </div>
    );
  }
);
