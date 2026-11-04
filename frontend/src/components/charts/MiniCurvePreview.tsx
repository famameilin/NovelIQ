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
import { getCSSColorVar } from "@/lib/theme";
import { cn } from "@/lib/cn";
import { useChartThemeSignature } from "@/hooks/useChartThemeSignature";
import type { EmotionTrendWindow } from "@/api/types";
import {
  formatEmotionTrendTooltipValue,
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

  const primaryColor = getCSSColorVar("--primary");

  const option = useMemo(() => {
    if (!data.length) return {};

    const seriesData = data.map(
      (window) => [window.position, window.smoothed_pooled_net_density] as const,
    );
    let densityMin = Infinity;
    let densityMax = -Infinity;
    for (const [, value] of seriesData) {
      if (value != null && Number.isFinite(value)) {
        densityMin = Math.min(densityMin, value);
        densityMax = Math.max(densityMax, value);
      }
    }
    if (densityMin === Infinity) {
      densityMin = -0.001;
      densityMax = 0.001;
    }
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
      series: [{
        name: "平滑趋势",
        type: "line" as const,
        data: seriesData,
        showSymbol: false,
        lineStyle: { width: 2, color: primaryColor },
      }],
    };
  }, [data, primaryColor]);

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
