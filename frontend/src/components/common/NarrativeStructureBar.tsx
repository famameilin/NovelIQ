import { ArrowRight, TrendingUp } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import {
  DashboardCardShell,
  getMetricAccentHoverTextClass,
} from "@/components/common/DashboardCardShell";
import { SegmentedBar } from "@/components/common/SegmentedBar";
import { cn } from "@/lib/cn";

/* ------------------------------------------------------------------ */
/*  类型定义                                                           */
/* ------------------------------------------------------------------ */

export interface NarrativeStructureBarProps {
  act1Ratio?: number | null;
  act2Ratio?: number | null;
  act3Ratio?: number | null;
  chapterNarrativeFunctionShare?: Record<string, number> | null;
  novelId: string;
  className?: string;
}

/* ------------------------------------------------------------------ */
/*  辅助函数                                                           */
/* ------------------------------------------------------------------ */

/**
 * 2026-08-16，任务：恢复叙事结构三段线
 * 作用：判断接口是否提供任一幕的结构比例
 */
function hasActData(
  act1: number | null | undefined,
  act2: number | null | undefined,
  act3: number | null | undefined,
): boolean {
  return act1 != null || act2 != null || act3 != null;
}

/**
 * 2026-08-16，任务：恢复叙事结构分段线
 * 作用：把接口提供的章节功能占比转换为分段线所需的数据
 */
function toShareSegments(
  share: Record<string, number> | null | undefined,
): { label: string; value: number; colorClass: string }[] {
  if (!share) return [];

  const colors = ["bg-chart-1", "bg-chart-2", "bg-chart-3"];
  return Object.entries(share)
    .filter(([, value]) => Number.isFinite(value) && value >= 0)
    .map(([label, value], index) => ({
      label,
      value: Math.round(value * 100),
      colorClass: colors[index % colors.length],
    }))
    .filter((segment) => segment.value > 0);
}

/* ------------------------------------------------------------------ */
/*  组件主体                                                           */
/* ------------------------------------------------------------------ */

/**
 * 2026-04-21，任务：仪表盘组件视觉重构
 * 修改原因：让叙事结构概览卡复用共享卡片壳，与其他仪表盘业务卡片保持一致
 */
export function NarrativeStructureBar({
  act1Ratio,
  act2Ratio,
  act3Ratio,
  chapterNarrativeFunctionShare,
  novelId,
  className,
}: NarrativeStructureBarProps) {
  const navigate = useNavigate();

  const actData = hasActData(act1Ratio, act2Ratio, act3Ratio);
  const actSegments = actData
    ? [
        { label: "引入", value: Math.round((act1Ratio ?? 0) * 100), colorClass: "bg-chart-1" },
        { label: "发展", value: Math.round((act2Ratio ?? 0) * 100), colorClass: "bg-chart-2" },
        { label: "收束", value: Math.round((act3Ratio ?? 0) * 100), colorClass: "bg-chart-3" },
      ]
    : [];
  const hasUsableActData = actSegments.some((segment) => segment.value > 0);
  const segments = hasUsableActData ? actSegments : toShareSegments(chapterNarrativeFunctionShare);
  const hasData = segments.length > 0;

  return (
    <DashboardCardShell
      title="叙事结构概览"
      icon={<TrendingUp className="h-5 w-5" />}
      accent="chart-1"
      className={cn(className)}
      bodyClassName="gap-3"
      footer={
        <Button
          variant="ghost"
          size="sm"
          onClick={() => navigate(`/novels/${novelId}/timeline`)}
          className={cn(
            "group flex items-center gap-1 px-0 text-xs text-text-muted transition-colors",
            getMetricAccentHoverTextClass("chart-1")
          )}
        >
          查看叙事时间轴
          <ArrowRight className="h-3 w-3 transition-transform group-hover:translate-x-0.5" />
        </Button>
      }
    >
      {hasData ? (
        <div className="rounded-2xl border border-border/70 bg-surface/75 p-3.5 shadow-sm">
          <SegmentedBar segments={segments} />
        </div>
      ) : (
        <p className="rounded-xl border border-dashed border-border bg-surface/60 px-3 py-2.5 text-xs text-text-muted">
          暂无数据
        </p>
      )}
    </DashboardCardShell>
  );
}
