import { DashboardCardShell } from "@/components/common/DashboardCardShell";
import { cn } from "@/lib/cn";
import { Scale } from "lucide-react";
import { DiagnosisPagedText } from "./DiagnosisPagedText";

export interface ValueLogicCardProps {
  /** 价值逻辑类型 */
  valueLogicType?: string | null;
  /** 价值逻辑原因说明 */
  valueLogicReason?: string | null;
  /** 当前报告的相关诊断与评分依据，和价值逻辑一起供连续阅读 */
  contextText?: string | null;
  className?: string;
}

/**
 * 2026-04-21，任务：多页面卡片风格统一
 * 修改原因：让诊断页的价值逻辑卡复用共享卡片壳，避免继续保留普通 Card 的旧视觉
 */
export function ValueLogicCard({
  valueLogicType,
  valueLogicReason,
  contextText,
  className,
}: ValueLogicCardProps) {
  return (
    <DashboardCardShell
      title={contextText ? "价值与主题诊断" : "价值逻辑"}
      icon={<Scale className="h-4 w-4" />}
      accent="chart-2"
      showOrb
      className={cn(className)}
      contentClassName="min-h-0 [&>div:first-child]:shrink-0"
      bodyClassName="min-h-0 flex-1 gap-2"
    >
      {valueLogicType || valueLogicReason || contextText ? (
        <div className="flex min-h-0 flex-1 flex-col gap-2">
          {valueLogicType && <div className="inline-flex w-fit shrink-0 items-center rounded-full bg-chart-2/12 px-3 py-1 text-sm font-medium text-chart-2">
            {valueLogicType}
          </div>}
          <DiagnosisPagedText key={`${valueLogicReason}-${contextText}`} text={[valueLogicReason, contextText].filter(Boolean).join("\n\n")} label="价值主题" testId="value-logic-passage" className="text-base leading-7" />
        </div>
      ) : (
        <p className="text-sm text-text-muted">暂无价值逻辑数据</p>
      )}
    </DashboardCardShell>
  );
}
