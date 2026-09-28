/** 段落主题权重按等长字符区间聚合；每行一个主题，避免逐段堆积产生高频色条。 */
import { useMemo } from "react";
import ReactEChartsCore from "echarts-for-react";
import * as echarts from "echarts/core";
import { HeatmapChart } from "echarts/charts";
import { GridComponent, TooltipComponent, VisualMapComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { useChartThemeSignature } from "@/hooks/useChartThemeSignature";
import { useInView } from "@/hooks/useInView";
import { buildTopicEvolutionWindows } from "@/lib/topicEvolution";
import type { TopicSeriesPoint } from "@/api/types";

echarts.use([GridComponent, TooltipComponent, VisualMapComponent, HeatmapChart, CanvasRenderer]);

interface TopicSeriesChartProps {
  points: TopicSeriesPoint[];
  numTopics: number;
  topicLabels?: Record<number, string>;
  className?: string;
}

export function TopicSeriesChart({ points, numTopics, topicLabels = {}, className }: TopicSeriesChartProps) {
  const themeSignature = useChartThemeSignature();
  const { ref: containerRef, isVisible } = useInView(0.05);
  const windows = useMemo(() => buildTopicEvolutionWindows(points, numTopics), [points, numTopics]);

  const option = useMemo(() => {
    const values = windows.flatMap((window) => window.weights ?? []).sort((left, right) => left - right);
    // 少数极高权重不应让其余主题全部显示为近乎空白；tooltip 始终给出原值。
    const colorMax = Math.max(0.05, values[Math.floor(values.length * 0.95)] ?? 0.05);
    const data: Array<[number, number, number]> = [];
    windows.forEach((window, windowIndex) => {
      window.weights?.forEach((weight, topicId) => data.push([windowIndex, numTopics - topicId - 1, weight]));
    });

    return {
      animation: false,
      tooltip: {
        trigger: "item",
        position: "top",
        formatter: (params: { value: [number, number, number] }) => {
          const [windowIndex, rowIndex, weight] = params.value;
          const topicId = numTopics - rowIndex - 1;
          const window = windows[windowIndex];
          const label = topicLabels[topicId] || `主题 ${topicId + 1}`;
          return `${label}<br/>字符 ${window.start.toLocaleString("zh-CN")}–${window.end.toLocaleString("zh-CN")}`
            + `<br/>加权占比 ${(weight * 100).toFixed(2)}% · ${window.paragraphCount} 段`
            + `<br/>入模词元 ${window.tokenTotal.toLocaleString("zh-CN")}`;
        },
      },
      grid: { left: 94, right: 20, top: 12, bottom: 40 },
      xAxis: {
        type: "category",
        data: windows.map((window) => String(window.start)),
        name: "字符位置",
        nameTextStyle: { fontSize: 10 },
        axisLabel: {
          fontSize: 10,
          interval: (index: number) => index % Math.max(1, Math.ceil(windows.length / 8)) === 0,
          formatter: (value: string) => Number(value).toLocaleString("zh-CN"),
        },
      },
      yAxis: {
        type: "category",
        data: Array.from({ length: numTopics }, (_, row) => {
          const topicId = numTopics - row - 1;
          return topicLabels[topicId] || `主题 ${topicId + 1}`;
        }),
        axisLabel: { fontSize: 10, width: 80, overflow: "truncate" },
      },
      visualMap: {
        show: false,
        min: 0,
        max: colorMax,
        inRange: { color: ["#f6ebe9", "#e7b0a5", "#c94e3d"] },
      },
      series: [{ type: "heatmap", data, progressive: 1000, emphasis: { itemStyle: { borderColor: "#333", borderWidth: 1 } } }],
    };
  }, [windows, numTopics, topicLabels]);

  return (
    <div ref={containerRef} className={className}>
      {windows.length === 0 ? (
        <div className="flex h-full items-center justify-center text-sm text-text-muted">暂无段落主题权重</div>
      ) : isVisible ? (
        <ReactEChartsCore key={themeSignature} option={option} notMerge style={{ height: "100%", width: "100%" }} />
      ) : (
        <div className="flex h-full items-center justify-center text-sm text-text-muted">图表加载中</div>
      )}
    </div>
  );
}
