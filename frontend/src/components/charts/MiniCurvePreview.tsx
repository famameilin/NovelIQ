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
import type { ParagraphCurvePoint } from "@/api/types";

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
  data: ParagraphCurvePoint[];
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

    const posData = data.map((d) => [d.position, d.pos_density] as [number, number | null]);
    const negData = data.map((d) => [d.position, d.neg_density] as [number, number | null]);
    const netData = data.map((d) => [d.position, d.net_density] as [number, number | null]);
    const smoothedData = data.map((d) => [d.position, d.smoothed_net_density] as [number, number | null]);

    return {
      grid: { top: 10, right: 10, bottom: 10, left: 10, containLabel: false },
      tooltip: {
        trigger: "axis" as const,
        axisPointer: { type: "cross" as const },
        backgroundColor: "hsl(var(--surface))",
        borderColor: "hsl(var(--border))",
        textStyle: { color: "hsl(var(--text))", fontSize: 11 },
        formatter: (params: Array<{ seriesName: string; value: number | null; marker: string; dataIndex?: number }>) => {
          if (!Array.isArray(params)) return "";
          const point = data[params[0]?.dataIndex ?? -1];
          if (!point) return "";
          return `第 ${point.chapter_id} 章 第 ${point.paragraph_index + 1} 段<br/>`
            + params.map((p) => `${p.marker} ${p.seriesName}: ${typeof p.value === "number" ? p.value.toFixed(4) : "-"}`).join("<br/>");
        },
      },
      xAxis: {
        type: "value",
        min: 0,
        max: 1,
        show: false,
      },
      yAxis: { type: "value", show: false, min: -1, max: 1 },
      series: [
        {
          name: "正向强度",
          type: "line",
          data: posData,
          smooth: true,
          showSymbol: false,
          lineStyle: { width: 1.2, color: hslToHsla(positiveColor, 0.28) },
          animationDuration: 800,
        },
        {
          name: "负向强度",
          type: "line",
          data: negData,
          smooth: true,
          showSymbol: false,
          lineStyle: { width: 1.2, color: hslToHsla(negativeColor, 0.28) },
          animationDuration: 800,
          animationDelay: 100,
        },
        {
          name: "原始趋势",
          type: "line",
          data: netData,
          smooth: true,
          showSymbol: false,
          lineStyle: { width: 1.4, color: hslToHsla(neutralColor, 0.5), type: "dashed" },
          animationDuration: 800,
          animationDelay: 140,
        },
        {
          name: "平滑趋势",
          type: "line",
          data: smoothedData,
          smooth: true,
          showSymbol: false,
          lineStyle: { width: 2.4, color: primaryColor },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: hslToHsla(primaryColor, 0.12) },
              { offset: 1, color: hslToHsla(primaryColor, 0.01) },
            ]),
          },
          animationDuration: 800,
          animationDelay: 180,
        },
      ],
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
