/**
 * TopicShiftsPanel - 主题迁移候选点（赛道 D /topics/shifts）
 *
 * 相邻不重叠窗口分布的 JS 散度（以 2 为底、[0,1]）；候选点不直接等同
 * 情节转折，需与事件和人工样本联合验证。展示散点定位 + 配置回显 + 明细表。
 */
import { useMemo, useState } from "react";
import ReactEChartsCore from "echarts-for-react";
import * as echarts from "echarts/core";
import { ScatterChart } from "echarts/charts";
import { GridComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { DashboardCardShell } from "@/components/common/DashboardCardShell";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useChartThemeSignature } from "@/hooks/useChartThemeSignature";
import { useInView } from "@/hooks/useInView";
import { cn } from "@/lib/cn";
import type { TopicShiftCandidate, TopicShiftConfig } from "@/api/types";

echarts.use([GridComponent, TooltipComponent, ScatterChart, CanvasRenderer]);

interface TopicShiftsPanelProps {
  candidates: TopicShiftCandidate[];
  config: TopicShiftConfig | null;
  showConfig?: boolean;
  className?: string;
}

export function TopicShiftsPanel({ candidates, config, showConfig = true, className }: TopicShiftsPanelProps) {
  const themeSignature = useChartThemeSignature();
  const { ref: chartContainerRef, isVisible: isChartVisible } = useInView(0.05);
  const [expandedCandidates, setExpandedCandidates] = useState<TopicShiftCandidate[] | null>(null);
  const showAllCandidates = expandedCandidates === candidates;
  const rankedCandidates = useMemo(
    () => [...candidates].sort((left, right) => right.score - left.score),
    [candidates],
  );
  const visibleCandidates = showAllCandidates ? rankedCandidates : rankedCandidates.slice(0, 8);

  const option = useMemo(
    () => ({
      tooltip: {
        formatter: (params: { data: [number, number] }) =>
          `位置 ${params.data[0]}<br/>主题差异强度 ${params.data[1]}`,
      },
      grid: { left: 56, right: 20, top: 24, bottom: 36 },
      xAxis: {
        type: "value",
        name: "字符位置",
        nameTextStyle: { fontSize: 10 },
        axisLabel: { fontSize: 10 },
      },
      yAxis: { type: "value", max: 1, axisLabel: { fontSize: 10 } },
      series: [
        {
          type: "scatter",
          symbolSize: 12,
          data: candidates.map((candidate) => [candidate.position, candidate.score]),
        },
      ],
    }),
    [candidates],
  );

  return (
    <div className={cn("flex h-full min-h-0 flex-col", className)}>
      <div className="grid min-h-0 flex-1 grid-cols-2 gap-4">
        <DashboardCardShell title="主题变化位置" accent="chart-2" className="h-full" contentClassName="flex h-full flex-col" bodyClassName="min-h-[280px] flex-1">
          <div ref={chartContainerRef} className="h-full min-h-[280px] w-full">
            {candidates.length === 0 ? (
              <p className="flex h-full items-center justify-center text-sm text-text-muted">无达到阈值的候选点</p>
            ) : isChartVisible ? (
              <ReactEChartsCore key={themeSignature} option={option} notMerge style={{ height: "100%", width: "100%" }} />
            ) : (
              <p className="flex h-full items-center justify-center text-sm text-text-muted">图表加载中</p>
            )}
          </div>
        </DashboardCardShell>

        <DashboardCardShell title="变化明细" accent="chart-4" className="h-full" contentClassName="flex h-full flex-col" bodyClassName="min-h-0 flex-1">
          {candidates.length === 0 ? (
            <p className="flex h-full items-center justify-center text-sm text-text-muted">暂无候选点</p>
          ) : (
            <div className="min-h-0 flex-1 overflow-y-auto pr-1">
              <Table className="text-left text-sm">
                <TableHeader className="sticky top-0 z-10 bg-surface">
                  <TableRow className="text-xs text-text-muted hover:bg-transparent">
                    <TableHead className="h-auto px-0 pb-2">字符位置</TableHead>
                    <TableHead className="h-auto px-0 pb-2">段落区间</TableHead>
                    <TableHead className="h-auto px-0 pb-2">差异强度</TableHead>
                    <TableHead className="h-auto px-0 pb-2">窗口词元</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {visibleCandidates.map((candidate) => (
                    <TableRow key={`${candidate.position}-${candidate.paragraph_start}`} className="border-border/40">
                      <TableCell className="px-0 py-1.5">{candidate.position}</TableCell>
                      <TableCell className="px-0 py-1.5">
                        {candidate.paragraph_start} – {candidate.paragraph_end}
                      </TableCell>
                      <TableCell className="px-0 py-1.5">{candidate.score.toFixed(4)}</TableCell>
                      <TableCell className="px-0 py-1.5">{candidate.window_token_total}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
          {candidates.length > 8 ? (
            <button
              type="button"
              onClick={() => setExpandedCandidates((current) => current === candidates ? null : candidates)}
              className="mt-3 rounded-md border border-border/60 px-3 py-1.5 text-xs text-text-muted hover:bg-surface-hover hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/45"
            >
              {showAllCandidates ? "收起完整明细" : `查看全部 ${candidates.length} 个变化位置`}
            </button>
          ) : null}
        </DashboardCardShell>
      </div>

      {showConfig && config && (
        <p className="mt-2 text-xs text-text-muted">
          计算配置：窗口 {config.window_size} 段 · 每窗最少 {config.min_tokens_per_window} 词元 ·
          阈值 {config.score_threshold} · 候选上限 {config.max_candidates}
        </p>
      )}
    </div>
  );
}
