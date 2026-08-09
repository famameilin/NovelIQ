import { AlertCircle, AlertTriangle } from "lucide-react";

import { DashboardCardShell } from "@/components/common/DashboardCardShell";

type AnalysisNotCompleteStateProps = {
  title?: string;
  description: string;
  /**
   * 2026-08-08 用于区分“仍在分析中”（等待态）与“任务已失败”（失败态），
   * 失败态用红色警示视觉，避免用户误以为任务还在正常推进
   */
  failed?: boolean;
};

/**
 * 结果子页面需要把 `AnalysisNotCompleteError` 渲染成明确的状态机提示，
 * 不能再混成通用“加载失败”；这里抽成共享卡片，保证多页文案和视觉保持一致
 */
export function AnalysisNotCompleteState({
  title = "分析尚未完成",
  description,
  failed = false,
}: AnalysisNotCompleteStateProps) {
  return (
    <DashboardCardShell
      title={title}
      icon={failed ? <AlertTriangle className="h-4 w-4" /> : <AlertCircle className="h-4 w-4" />}
      accent="chart-4"
      className="min-h-[240px]"
      bodyClassName="items-center justify-center gap-3 text-center"
    >
      {failed ? (
        <AlertTriangle className="h-12 w-12 text-chart-negative" />
      ) : (
        <AlertCircle className="h-12 w-12 text-text-muted" />
      )}
      <p className="text-sm text-text-muted">{description}</p>
    </DashboardCardShell>
  );
}
