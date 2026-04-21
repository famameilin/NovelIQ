import { DashboardCardShell } from "@/components/common/DashboardCardShell";
import { cn } from "@/lib/cn";
import { Scale } from "lucide-react";

export interface ValueLogicCardProps {
  /** 价值逻辑类型 */
  valueLogicType?: string | null;
  /** 价值逻辑原因说明 */
  valueLogicReason?: string | null;
  className?: string;
}

/**
 * 2026-04-21，任务：多页面卡片风格统一
 * 修改原因：让诊断页的价值逻辑卡复用共享卡片壳，避免继续保留普通 Card 的旧视觉。
 */
export function ValueLogicCard({
  valueLogicType,
  valueLogicReason,
  className,
}: ValueLogicCardProps) {
  return (
    <DashboardCardShell
      title="价值逻辑"
      icon={<Scale className="h-4 w-4" />}
      accent="chart-2"
      showOrb
      className={cn(className)}
      bodyClassName="gap-3"
    >
      {valueLogicType ? (
        <div className="flex flex-col gap-3">
          <div className="inline-flex w-fit items-center rounded-full bg-chart-2/12 px-3 py-1.5 text-sm font-medium text-chart-2">
            {valueLogicType}
          </div>
          {valueLogicReason && (
            <div className="rounded-2xl border border-border/60 bg-surface/70 px-4 py-3">
              <p className="text-xs leading-6 text-text-muted">{valueLogicReason}</p>
            </div>
          )}
        </div>
      ) : (
        <p className="text-sm text-text-muted">暂无价值逻辑数据</p>
      )}
    </DashboardCardShell>
  );
}
