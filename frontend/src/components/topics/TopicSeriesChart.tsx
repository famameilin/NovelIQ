/**
 * TopicSeriesChart - 主题演进堆积面积图（赛道 D /topics/series）
 *
 * 每段完整 K 维权重，x 轴为真实字符位置；堆积面积展示主题构成随情节推进
 * 的变化。展示层降采样交给 echarts sampling:'lttb'，不改动后端口径。
 */
import { useMemo } from "react";
import ReactEChartsCore from "echarts-for-react";
import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import { GridComponent, TooltipComponent, LegendComponent, DataZoomComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { useChartThemeSignature } from "@/hooks/useChartThemeSignature";
import { useInView } from "@/hooks/useInView";
import type { TopicSeriesPoint } from "@/api/types";

echarts.use([GridComponent, TooltipComponent, LegendComponent, DataZoomComponent, LineChart, CanvasRenderer]);

interface TopicSeriesChartProps {
  points: TopicSeriesPoint[];
  numTopics: number;
  className?: string;
}

export function TopicSeriesChart({ points, numTopics, className }: TopicSeriesChartProps) {
  const themeSignature = useChartThemeSignature();
  const { ref: containerRef, isVisible } = useInView(0.05);

  const option = useMemo(() => {
    const series = Array.from({ length: numTopics }, (_, topicId) => ({
      name: `主题 ${topicId + 1}`,
      type: "line" as const,
      stack: "distribution",
      sampling: "lttb" as const,
      showSymbol: false,
      lineStyle: { width: 0.5 },
      areaStyle: { opacity: 0.85 },
      emphasis: { focus: "series" as const },
      data: points.map((point) => [point.start_position, point.weights[topicId] ?? 0]),
    }));

    return {
      tooltip: {
        trigger: "axis",
        valueFormatter: (value: unknown) => (typeof value === "number" ? value.toFixed(3) : String(value ?? "-")),
      },
      legend: { type: "scroll", bottom: 0, textStyle: { fontSize: 10 } },
      grid: { left: 56, right: 20, top: 24, bottom: 64 },
      xAxis: {
        type: "value",
        name: "字符位置",
        nameTextStyle: { fontSize: 10 },
        axisLabel: { fontSize: 10, formatter: (value: number) => String(value) },
        min: (value: { min: number }) => value.min,
        max: (value: { max: number }) => value.max,
      },
      yAxis: {
        type: "value",
        max: 1,
        axisLabel: { fontSize: 10 },
      },
      dataZoom: [{ type: "inside" }],
      series,
    };
  }, [points, numTopics]);

  return (
    <div ref={containerRef} className={className}>
      {isVisible ? (
        <ReactEChartsCore key={themeSignature} option={option} notMerge style={{ height: "100%", width: "100%" }} />
      ) : (
        <div className="flex h-full items-center justify-center text-sm text-text-muted">图表加载中</div>
      )}
    </div>
  );
}
