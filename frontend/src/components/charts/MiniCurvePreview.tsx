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
import type { ChunkCurvePoint } from "@/api/types";

echarts.use([
  GridComponent,
  TooltipComponent,
  LineChart,
  CanvasRenderer,
]);

/* ------------------------------------------------------------------ */
/*  Types                                                             */
/* ------------------------------------------------------------------ */

export interface MiniCurvePreviewProps {
  data: ChunkCurvePoint[];
  novelId: string;
  className?: string;
}

/* ------------------------------------------------------------------ */
/*  Component                                                         */
/* ------------------------------------------------------------------ */

export function MiniCurvePreview({
  data,
  novelId,
  className,
}: MiniCurvePreviewProps) {
  const navigate = useNavigate();

  const positiveColor = getCSSColorVar("--chart-positive");
  const negativeColor = getCSSColorVar("--chart-negative");

  const option = useMemo(() => {
    if (!data.length) return {};

    const xData = data.map((d) => d.chunk_id);
    const posData = data.map((d) => d.pos_density ?? 0);
    const negData = data.map((d) => d.neg_density ?? 0);

    return {
      grid: { top: 10, right: 10, bottom: 10, left: 10, containLabel: false },
      tooltip: {
        trigger: "axis" as const,
        axisPointer: { type: "cross" as const },
        backgroundColor: "hsl(var(--surface))",
        borderColor: "hsl(var(--border))",
        textStyle: { color: "hsl(var(--text))", fontSize: 11 },
        formatter: (params: Array<{ seriesName: string; value: number; marker: string; axisValue?: string }>) => {
          if (!Array.isArray(params)) return "";
          return `分块 ${params[0]?.axisValue ?? ""}<br/>`
            + params.map((p) => `${p.marker} ${p.seriesName}: ${p.value.toFixed(4)}`).join("<br/>");
        },
      },
      xAxis: {
        type: "category",
        data: xData,
        show: false,
        boundaryGap: false,
      },
      yAxis: { type: "value", show: false },
      series: [
        {
          name: "正面密度",
          type: "line",
          data: posData,
          smooth: true,
          showSymbol: false,
          lineStyle: { width: 1.5, color: positiveColor },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: hslToHsla(positiveColor, 0.15) },
              { offset: 1, color: hslToHsla(positiveColor, 0.01) },
            ]),
          },
          animationDuration: 800,
        },
        {
          name: "负面密度",
          type: "line",
          data: negData,
          smooth: true,
          showSymbol: false,
          lineStyle: { width: 1.5, color: negativeColor },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: hslToHsla(negativeColor, 0.15) },
              { offset: 1, color: hslToHsla(negativeColor, 0.01) },
            ]),
          },
          animationDuration: 800,
          animationDelay: 100,
        },
      ],
    };
  }, [data, positiveColor, negativeColor]);

  return (
    <Card
      className={cn(
        "group cursor-pointer border-border/60 transition-colors hover:border-primary/30",
        className,
      )}
      onClick={() => navigate(`/novels/${novelId}/curves`)}
    >
      <div className="px-5 pt-4 pb-2">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-text">情绪曲线</h3>
          <span className="text-xs text-text-muted opacity-0 transition-opacity group-hover:opacity-100">
            查看完整曲线 →
          </span>
        </div>
      </div>
      <div className="h-[150px] w-full">
        {data.length > 0 ? (
          <ReactEChartsCore
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
