/**
 * TopicShiftsPanel - 主题迁移候选点（赛道 D /topics/shifts）
 *
 * 相邻不重叠窗口分布的 JS 散度（以 2 为底、[0,1]）；候选点不直接等同
 * 情节转折，需与事件和人工样本联合验证。展示散点定位 + 配置回显 + 明细表。
 */
import { useMemo } from "react";
import ReactEChartsCore from "echarts-for-react";
import * as echarts from "echarts/core";
import { ScatterChart } from "echarts/charts";
import { GridComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { DashboardCardShell } from "@/components/common/DashboardCardShell";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useChartThemeSignature } from "@/hooks/useChartThemeSignature";
import type { TopicShiftCandidate, TopicShiftConfig } from "@/api/types";

echarts.use([GridComponent, TooltipComponent, ScatterChart, CanvasRenderer]);

interface TopicShiftsPanelProps {
  candidates: TopicShiftCandidate[];
  config: TopicShiftConfig | null;
  className?: string;
}

export function TopicShiftsPanel({ candidates, config, className }: TopicShiftsPanelProps) {
  const themeSignature = useChartThemeSignature();

  const option = useMemo(
    () => ({
      tooltip: {
        formatter: (params: { data: [number, number] }) =>
          `位置 ${params.data[0]}<br/>JS 散度 ${params.data[1]}`,
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
    <div className={className}>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <DashboardCardShell title="候选点分布" accent="chart-2" bodyClassName="min-h-[280px]">
          {candidates.length === 0 ? (
            <p className="flex h-full items-center justify-center text-sm text-text-muted">无达到阈值的候选点</p>
          ) : (
            <ReactEChartsCore key={themeSignature} option={option} notMerge style={{ height: "100%", width: "100%" }} />
          )}
        </DashboardCardShell>

        <DashboardCardShell title="候选明细" accent="chart-4" bodyClassName="min-h-[280px] overflow-y-auto">
          {candidates.length === 0 ? (
            <p className="flex h-full items-center justify-center text-sm text-text-muted">暂无候选点</p>
          ) : (
            <Table className="text-left text-sm">
              <TableHeader>
                <TableRow className="text-xs text-text-muted hover:bg-transparent">
                  <TableHead className="h-auto px-0 pb-2">字符位置</TableHead>
                  <TableHead className="h-auto px-0 pb-2">段落区间</TableHead>
                  <TableHead className="h-auto px-0 pb-2">JS 散度</TableHead>
                  <TableHead className="h-auto px-0 pb-2">窗口 token</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {candidates.map((candidate) => (
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
          )}
        </DashboardCardShell>
      </div>

      {config && (
        <p className="mt-2 text-xs text-text-muted">
          版本化配置：窗口 {config.window_size} 段 · 每窗最少 {config.min_tokens_per_window} token ·
          阈值 {config.score_threshold} · 候选上限 {config.max_candidates}
        </p>
      )}
    </div>
  );
}
