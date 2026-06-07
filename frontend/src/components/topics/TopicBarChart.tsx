/**
 * TopicBarChart - 主题权重柱状图组件
 *
 * 基于 ECharts 的横向柱状图，展示各主题权重排名，悬浮显示关键词
 */
import { useMemo } from "react";
import ReactEChartsCore from "echarts-for-react";
import * as echarts from "echarts/core";
import { BarChart } from "echarts/charts";
import {
  GridComponent,
  TooltipComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { BarChart3 } from "lucide-react";
import { DashboardCardShell } from "@/components/common/DashboardCardShell";
import { getCSSColorVar } from "@/lib/theme";
import { CHART_COLORS } from "@/lib/chart-colors";
import { cn } from "@/lib/cn";
import { useChartThemeSignature } from "@/hooks/useChartThemeSignature";
import { useInView } from "@/hooks/useInView";
import type { Topic } from "@/api/types";

echarts.use([GridComponent, TooltipComponent, BarChart, CanvasRenderer]);

export interface TopicBarChartProps {
  topics: Topic[];
  className?: string;
}

export function TopicBarChart({ topics, className }: TopicBarChartProps) {
  const themeSignature = useChartThemeSignature();
  const { ref: containerRef, isVisible } = useInView(0.1);

  const chartColors = useMemo(() => {
    return CHART_COLORS.map((c) => getCSSColorVar(c));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- themeSignature triggers re-computation on theme change
  }, [themeSignature]);

  const sortedTopics = useMemo(() => {
    return [...topics].sort((a, b) => b.weight - a.weight);
  }, [topics]);

  const option = useMemo(() => {
    if (sortedTopics.length === 0) return {};

    const labels = [...sortedTopics].map((t) =>
      t.label || `主题 ${t.topic_id + 1}`
    );
    const weights = [...sortedTopics].map((t) => t.weight);
    const colors = [...sortedTopics].map((t) =>
      chartColors[t.topic_id % chartColors.length]
    );

    return {
      grid: { top: 10, right: 60, bottom: 10, left: 80, containLabel: false },
      tooltip: {
        trigger: "axis" as const,
        axisPointer: { type: "shadow" as const },
        backgroundColor: "hsl(var(--surface))",
        borderColor: "hsl(var(--border))",
        textStyle: { color: "hsl(var(--text))", fontSize: 12 },
        formatter: (params: Array<{ dataIndex: number; marker: string }>) => {
          const p = params[0];
          const topic = sortedTopics[p.dataIndex];
          const topWords = topic.words.slice(0, 5).join(", ");
          return `<div style="max-width: 200px">
            <div style="font-weight: 600; margin-bottom: 4px">${topic.label || `主题 ${topic.topic_id + 1}`}</div>
            <div>${p.marker} 权重: ${(topic.weight * 100).toFixed(1)}%</div>
            <div style="color: hsl(var(--text-muted)); font-size: 11px; margin-top: 4px">关键词: ${topWords}</div>
          </div>`;
        },
      },
      xAxis: {
        type: "value" as const,
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: {
          color: "hsl(var(--text-muted))",
          fontSize: 11,
          formatter: (value: number) => `${(value * 100).toFixed(0)}%`,
        },
        splitLine: { lineStyle: { color: "hsl(var(--border))", type: "dashed" } },
      },
      yAxis: {
        type: "category" as const,
        data: labels,
        inverse: true,
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: {
          color: "hsl(var(--text))",
          fontSize: 12,
        },
      },
      series: [
        {
          name: "权重",
          type: "bar",
          data: weights,
          barWidth: "50%",
          itemStyle: {
            borderRadius: [0, 4, 4, 0],
            color: (params: { dataIndex: number }) => colors[params.dataIndex],
          },
          label: {
            show: true,
            position: "right",
            formatter: (params: { value: number }) => `${(params.value * 100).toFixed(1)}%`,
            color: "hsl(var(--text-muted))",
            fontSize: 11,
          },
          animationDuration: 800,
          animationEasing: "cubicOut",
        },
      ],
    };
  }, [sortedTopics, chartColors]);

  const hasData = sortedTopics.length > 0;

  return (
    <DashboardCardShell
      title="主题权重分布"
      icon={<BarChart3 className="h-4 w-4" />}
      accent="chart-2"
      className={cn("h-full", className)}
      contentClassName="flex h-full flex-col"
      bodyClassName="flex-1 min-h-0 gap-3"
    >
      <div ref={containerRef} className="flex-1 min-h-0 w-full rounded-2xl border border-border/60 bg-surface/70 p-2">
        {hasData && isVisible ? (
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
            {hasData ? "加载中..." : "暂无主题数据"}
          </div>
        )}
      </div>
    </DashboardCardShell>
  );
}
