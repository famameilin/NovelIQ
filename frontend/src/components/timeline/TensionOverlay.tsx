/**
 * TensionOverlay - 张力曲线叠加面积图组件
 *
 * 使用 ECharts 实现张力曲线面积图，叠加在时间轴下方
 */

import { useRef, useEffect, useCallback } from "react";
import ReactEChartsCore from "echarts-for-react";
import * as echarts from "echarts";
import { cn } from "@/lib/cn";
import { getCSSColorVar, hslToHsla } from "@/lib/theme";
import { useChartThemeSignature } from "@/hooks/useChartThemeSignature";

/* ------------------------------------------------------------------ */
/*  类型定义                                                           */
/* ------------------------------------------------------------------ */

export interface TensionOverlayProps {
  tensionCurve: number[];
  totalChapters: number;
  height?: number;
  className?: string;
}

/* ------------------------------------------------------------------ */
/*  组件主体                                                           */
/* ------------------------------------------------------------------ */

export function TensionOverlay({
  tensionCurve,
  totalChapters,
  height = 120,
  className,
}: TensionOverlayProps) {
  const themeSignature = useChartThemeSignature();
  const chartRef = useRef<ReactEChartsCore>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // 获取当前主题色（不缓存：确保主题切换时颜色同步更新）
  // getCSSColorVar 内部已做 DOM 查询优化（读一次 CSS 变量）
  const chartColor = getCSSColorVar("--chart-3") || "#888888";

  const handleResize = useCallback(() => {
    chartRef.current?.getEchartsInstance()?.resize();
  }, []);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const observer = new ResizeObserver(handleResize);
    observer.observe(container);
    return () => observer.disconnect();
  }, [handleResize]);

  if (!tensionCurve || tensionCurve.length === 0) {
    return null;
  }

  const xData = tensionCurve.map((_, i) => i);
  const yData = tensionCurve;

  const safeTotalChapters = Math.max(1, totalChapters);

  // 动态计算 Y 轴范围，适配不同数据源（tension_proxy / tension_composite）
  const yMin = Math.min(...yData);
  const yMax = Math.max(...yData);
  const yPadding = Math.max((yMax - yMin) * 0.1, 0.01); // 至少 10% 边距

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
      max: safeTotalChapters - 1,
    },
    yAxis: {
      type: "value",
      show: false,
      min: yMin - yPadding,
      max: yMax + yPadding,
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
            { offset: 0, color: hslToHsla(chartColor, 0.25) },
            { offset: 1, color: hslToHsla(chartColor, 0.02) },
          ]),
        },
      },
    ],
    animationDuration: 800,
    animationEasing: "cubicOut",
  };

  return (
    <div ref={containerRef} className={cn("relative", className)}>
      <div className="absolute left-2 top-0 text-xs text-text-muted">
        张力曲线
      </div>
      <ReactEChartsCore
        key={themeSignature}
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
