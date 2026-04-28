import { AlertCircle } from "lucide-react";

import { DashboardCardShell } from "@/components/common/DashboardCardShell";

type AnalysisNotCompleteStateProps = {
  title?: string;
  description: string;
};

/**
 * 结果子页面需要把 `AnalysisNotCompleteError` 渲染成明确的状态机提示，
 * 不能再混成通用“加载失败”；这里抽成共享卡片，保证多页文案和视觉保持一致
 */
export function AnalysisNotCompleteState({
  title = "分析尚未完成",
  description,
}: AnalysisNotCompleteStateProps) {
  return (
    <DashboardCardShell
      title={title}
      icon={<AlertCircle className="h-4 w-4" />}
      accent="chart-4"
      className="min-h-[240px]"
      bodyClassName="items-center justify-center gap-3 text-center"
    >
      <AlertCircle className="h-12 w-12 text-text-muted" />
      <p className="text-sm text-text-muted">{description}</p>
    </DashboardCardShell>
  );
}
