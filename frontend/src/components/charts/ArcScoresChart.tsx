import { useMemo, useState } from "react";
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
import { PagedControls } from "@/components/common/PagedControls";
import { useDiagnosisCapacity } from "@/components/diagnosis/useDiagnosisCapacity";
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
 * 少量评分按人数确定高度，大量评分分页浏览，保留全部人物的可达性
 */
export function ArcScoresChart({ arcScores, className }: ArcScoresChartProps) {
  const themeSignature = useChartThemeSignature();
  const primaryColor = getCSSColorVar("--primary");
  const [page, setPage] = useState(1);
  const scoreCount = Object.keys(arcScores ?? {}).length;
  const { ref, capacity } = useDiagnosisCapacity(26, 56);
  const pageSize = Math.min(12, capacity);
  const pageCount = Math.ceil(scoreCount / pageSize);
  const currentPage = Math.min(page, Math.max(pageCount, 1));

  const option = useMemo(() => {
    if (!arcScores || Object.keys(arcScores).length === 0) {
      return {};
    }

    // 先对完整集合排序，再分页，避免仅按当前页排序改变排名口径
    const sortedEntries = Object.entries(arcScores)
      .sort(([, a], [, b]) => b - a)
      .slice((currentPage - 1) * pageSize, currentPage * pageSize);

    const names = sortedEntries.map(([name]) => name);
    const values = sortedEntries.map(([, score]) => score);

    return {
      grid: { top: 12, right: 48, bottom: 28, left: 12, containLabel: true },
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
        inverse: true,
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
          barMaxWidth: 20,
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
  }, [arcScores, primaryColor, currentPage, pageSize]);

  const hasData = arcScores && Object.keys(arcScores).length > 0;

  return (
    <DashboardCardShell
      title="角色弧线得分"
      icon={<GitBranch className="h-4 w-4" />}
      accent="chart-3"
      className={cn(className)}
      contentClassName="min-h-0 [&>div:first-child]:shrink-0"
      bodyClassName="min-h-0 flex-1 gap-2"
      headerRight={<span className="text-xs text-text-muted">{scoreCount} 人 · 满分 10</span>}
    >
      <div ref={ref} className="min-h-0 w-full flex-1 rounded-lg border border-border/60 bg-surface/70 p-2">
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
      <div className="h-8 shrink-0"><PagedControls page={currentPage} pageCount={pageCount} onPageChange={setPage} label="角色弧线" /></div>
    </DashboardCardShell>
  );
}
