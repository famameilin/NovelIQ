/**
 * TensionOverlay - 张力曲线叠加面积图组件
 *
 * 创建时间: 2026-04-05
 * 创建者: GLM-5
 * 任务: Phase 2-B 叙事时间轴
 * 说明: 使用 ECharts 实现张力曲线面积图，叠加在时间轴下方
 */

import { useRef } from "react";
import ReactEChartsCore from "echarts-for-react";
import * as echarts from "echarts";
import { cn } from "@/lib/cn";
import { getCSSColorVar } from "@/lib/theme";

/* ------------------------------------------------------------------ */
/*  Types                                                             */
/* ------------------------------------------------------------------ */

export interface TensionOverlayProps {
  tensionCurve: number[];
  totalChunks: number;
  height?: number;
  className?: string;
}

/* ------------------------------------------------------------------ */
/*  Component                                                         */
/* ------------------------------------------------------------------ */

export function TensionOverlay({
  tensionCurve,
  totalChunks,
  height = 120,
  className,
}: TensionOverlayProps) {
  const chartRef = useRef<ReactEChartsCore>(null);
  const chartColor = getCSSColorVar("--chart-3") || "#888888";

  if (!tensionCurve || tensionCurve.length === 0) {
    return null;
  }

  const xData = tensionCurve.map((_, i) => i);
  const yData = tensionCurve;

  const option: echarts.EChartsOption = {
    grid: {
      left: 0,
      right: 0,
      top: 10,
      bottom: 20,
    },
    xAxis: {
      type: "category",
      data: xData,
      show: false,
      min: 0,
      max: totalChunks - 1,
    },
    yAxis: {
      type: "value",
      show: false,
      min: 0,
      max: 1,
    },
    series: [
      {
        type: "line",
        data: yData,
        smooth: true,
        symbol: "none",
        lineStyle: {
          width: 2,
          color: chartColor,
        },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: `${chartColor}40` },
            { offset: 1, color: `${chartColor}05` },
          ]),
        },
      },
    ],
    animationDuration: 800,
    animationEasing: "cubicOut",
  };

  return (
    <div className={cn("relative", className)}>
      <div className="absolute left-2 top-0 text-xs text-text-muted">
        张力曲线
      </div>
      <ReactEChartsCore
        ref={chartRef}
        echarts={echarts}
        option={option}
        style={{ height: `${height}px`, width: "100%" }}
        opts={{ renderer: "canvas" }}
        notMerge={true}
      />
    </div>
  );
}
