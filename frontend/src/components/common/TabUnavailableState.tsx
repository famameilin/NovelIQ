import { AlertCircle } from "lucide-react";

import { DashboardCardShell } from "@/components/common/DashboardCardShell";

interface TabUnavailableStateProps {
  reason: string | null | undefined;
  title?: string;
  className?: string;
}

/**
 * tab 数据不可用空态：保留不可用信号，不直接暴露后端内部原因
 */
export function TabUnavailableState({ reason, title = "数据暂不可用", className }: TabUnavailableStateProps) {
  return (
    <DashboardCardShell
      title={title}
      icon={<AlertCircle className="h-4 w-4" />}
      accent="chart-4"
      className={className ?? "min-h-[240px]"}
      bodyClassName="items-center justify-center gap-2 text-center"
    >
      <AlertCircle className="h-12 w-12 text-text-muted" />
      <p className="text-sm text-text-muted">当前任务暂无可展示的结果数据。</p>
      {reason && <p className="max-w-md text-xs text-text-muted/80">分析数据源暂未满足当前视图的生成条件。</p>}
    </DashboardCardShell>
  );
}
