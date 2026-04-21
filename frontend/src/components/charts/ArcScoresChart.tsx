import { useMemo } from "react";
import ReactEChartsCore from "echarts-for-react";
import * as echarts from "echarts/core";
import { BarChart } from "echarts/charts";
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { GitBranch } from "lucide-react";
import { DashboardCardShell } from "@/components/common/DashboardCardShell";
import { getCSSColorVar, hslToHsla } from "@/lib/theme";
import { cn } from "@/lib/cn";
import { useChartThemeSignature } from "@/hooks/useChartThemeSignature";

echarts.use([GridComponent, TooltipComponent, LegendComponent, BarChart, CanvasRenderer]);

export interface ArcScoresChartProps {
  /** 角色弧线得分数据，key 为角色名，value 为得分 (0-10) */
  arcScores?: Record<string, number> | null;
  className?: string;
}

/**
 * 2026-04-21，任务：多页面卡片风格统一
 * 修改原因：把诊断页弧线图也接入共享卡片壳，避免图表页和信息卡页出现两套容器体系。
 */
export function ArcScoresChart({ arcScores, className }: ArcScoresChartProps) {
  const themeSignature = useChartThemeSignature();
  const primaryColor = getCSSColorVar("--primary");

  const option = useMemo(() => {
    if (!arcScores || Object.keys(arcScores).length === 0) {
      return {};
    }

    // 按得分排序，取前 10 个
    const sortedEntries = Object.entries(arcScores)
      .sort(([, a], [, b]) => b - a)
      .slice(0, 10);

    const names = sortedEntries.map(([name]) => name);
    const values = sortedEntries.map(([, score]) => score);

    return {
      grid: { top: 20, right: 20, bottom: 40, left: 60, containLabel: false },
      tooltip: {
        trigger: "axis" as const,
        axisPointer: { type: "shadow" as const },
        backgroundColor: "hsl(var(--surface))",
        borderColor: "hsl(var(--border))",
        textStyle: { color: "hsl(var(--text))", fontSize: 12 },
        formatter: (params: Array<{ name: string; value: number; marker: string }>) => {
          const p = params[0];
          return `${p.name}<br/>${p.marker} 弧线得分: ${p.value}/10`;
        },
      },
      xAxis: {
        type: "value" as const,
        max: 10,
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { color: "hsl(var(--text-muted))", fontSize: 11 },
        splitLine: { lineStyle: { color: "hsl(var(--border))", type: "dashed" } },
      },
      yAxis: {
        type: "category" as const,
        data: names,
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { color: "hsl(var(--text))", fontSize: 12 },
      },
      series: [
        {
          name: "弧线得分",
          type: "bar",
          data: values,
          barWidth: "60%",
          itemStyle: {
            borderRadius: [0, 4, 4, 0],
            color: new echarts.graphic.LinearGradient(0, 0, 1, 0, [
              { offset: 0, color: primaryColor },
              { offset: 1, color: hslToHsla(primaryColor, 0.7) },
            ]),
          },
          label: {
            show: true,
            position: "right",
            formatter: "{c}/10",
            color: "hsl(var(--text-muted))",
            fontSize: 11,
          },
          animationDuration: 800,
          animationEasing: "cubicOut",
        },
      ],
    };
  }, [arcScores, primaryColor]);

  const hasData = arcScores && Object.keys(arcScores).length > 0;

  return (
    <DashboardCardShell
      title="角色弧线得分"
      icon={<GitBranch className="h-4 w-4" />}
      accent="chart-3"
      className={cn(className)}
      bodyClassName="gap-3"
    >
      <div className="h-[300px] w-full rounded-2xl border border-border/60 bg-surface/70 p-2">
        {hasData ? (
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
            暂无弧线数据
          </div>
        )}
      </div>
    </DashboardCardShell>
  );
}
