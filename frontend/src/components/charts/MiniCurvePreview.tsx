import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import ReactEChartsCore from "echarts-for-react";
import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import {
  GridComponent,
  TooltipComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { Card } from "@/components/ui/card";
import { getCSSColorVar, hslToHsla } from "@/lib/theme";
import { cn } from "@/lib/cn";
import { useChartThemeSignature } from "@/hooks/useChartThemeSignature";
import type { EmotionTrendWindow } from "@/api/types";
import {
  EMOTION_TREND_SERIES_CONFIG,
  formatEmotionTrendTooltipValue,
  getEmotionTrendSeriesValue,
} from "./emotionTrendSeries";

echarts.use([
  GridComponent,
  TooltipComponent,
  LineChart,
  CanvasRenderer,
]);

/* ------------------------------------------------------------------ */
/*  类型定义                                                           */
/* ------------------------------------------------------------------ */

export interface MiniCurvePreviewProps {
  data: EmotionTrendWindow[];
  novelId: string;
  className?: string;
}

/* ------------------------------------------------------------------ */
/*  组件主体                                                           */
/* ------------------------------------------------------------------ */

export function MiniCurvePreview({
  data,
  novelId,
  className,
}: MiniCurvePreviewProps) {
  const navigate = useNavigate();
  const themeSignature = useChartThemeSignature();

  const positiveColor = getCSSColorVar("--chart-positive");
  const negativeColor = getCSSColorVar("--chart-negative");
  const neutralColor = getCSSColorVar("--chart-1");
  const primaryColor = getCSSColorVar("--primary");

  const option = useMemo(() => {
    if (!data.length) return {};

    const seriesData = EMOTION_TREND_SERIES_CONFIG.map((config) =>
      data.map((window) => [window.position, getEmotionTrendSeriesValue(window, config)] as [number, number | null]),
    );
    const colorMap: Record<string, string> = {
      "--chart-positive": positiveColor,
      "--chart-negative": negativeColor,
      "--chart-1": neutralColor,
      "--primary": primaryColor,
    };
    const densityValues = seriesData.flatMap((series) =>
      series.flatMap(([, value]) => (typeof value === "number" && Number.isFinite(value) ? [value] : [])),
    );
    const densityMin = densityValues.length > 0 ? Math.min(0, ...densityValues) : -0.001;
    const densityMax = densityValues.length > 0 ? Math.max(0, ...densityValues) : 0.001;
    const densitySpan = Math.max(densityMax - densityMin, 0.001);
    const densityPadding = densitySpan * 0.15;

    return {
      grid: { top: 10, right: 10, bottom: 10, left: 10, containLabel: false },
      tooltip: {
        trigger: "axis" as const,
        axisPointer: { type: "cross" as const },
        backgroundColor: "hsl(var(--surface))",
        borderColor: "hsl(var(--border))",
        textStyle: { color: "hsl(var(--text))", fontSize: 11 },
        formatter: (params: Array<{ seriesName: string; value: unknown; marker: string; dataIndex?: number }>) => {
          if (!Array.isArray(params)) return "";
          const point = data[params[0]?.dataIndex ?? -1];
          if (!point) return "";
          const chapterLabel =
            point.chapter_start === point.chapter_end
              ? `第 ${point.chapter_start} 章`
              : `第 ${point.chapter_start}~${point.chapter_end} 章`;
          return `${chapterLabel} · 第 ${point.paragraph_start + 1}~${point.paragraph_end + 1} 段（共 ${point.paragraph_total} 段）<br/>`
            + params.map((p) => `${p.marker} ${p.seriesName}: ${formatEmotionTrendTooltipValue(p.value)}`).join("<br/>");
        },
      },
      xAxis: {
        type: "value",
        min: 0,
        max: 1,
        show: false,
      },
      yAxis: {
        type: "value",
        show: false,
        min: densityMin - densityPadding,
        max: densityMax + densityPadding,
      },
      series: EMOTION_TREND_SERIES_CONFIG.map((config, index) => {
        const color = colorMap[config.colorVar];
        const isMainSeries = config.role === "main";
        const isSupportSeries = config.role === "support";
        const lineOpacity = isMainSeries ? 1 : isSupportSeries ? 0.55 : 0.38;
        return {
          name: config.name,
          type: "line" as const,
          data: seriesData[index],
          smooth: true,
          showSymbol: false,
          z: isMainSeries ? 4 : isSupportSeries ? 3 : 2,
          lineStyle: {
            width: isMainSeries ? 3 : isSupportSeries ? 2 : 1.5,
            color: hslToHsla(color, lineOpacity),
            type: isSupportSeries ? "dashed" : "solid",
          },
          areaStyle: isMainSeries
            ? {
                color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                  { offset: 0, color: hslToHsla(color, 0.12) },
                  { offset: 1, color: hslToHsla(color, 0.01) },
                ]),
              }
            : undefined,
          animationDuration: 800,
        };
      }),
    };
  }, [data, negativeColor, neutralColor, positiveColor, primaryColor]);

  return (
    <Card
      className={cn(
        "group cursor-pointer border-border/60 transition-colors hover:border-primary/30",
        className,
      )}
      onClick={() => navigate(`/novels/${novelId}/curves`)}
    >
      <div className="px-4 pt-3 pb-1.5">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-text">情绪趋势</h3>
          <span className="text-xs text-text-muted opacity-0 transition-opacity group-hover:opacity-100">
            查看完整曲线 →
          </span>
        </div>
      </div>
      <div className="h-[132px] w-full">
        {data.length > 0 ? (
          <ReactEChartsCore
            key={themeSignature}
            echarts={echarts}
            option={option}
            style={{ height: "100%", width: "100%" }}
            notMerge
            lazyUpdate
          />
        ) : (
          <div className="flex h-full items-center justify-center text-sm text-text-muted">
            暂无曲线数据
          </div>
        )}
      </div>
    </Card>
  );
}
