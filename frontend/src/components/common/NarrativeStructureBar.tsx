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
  eventDensity?: Record<string, number> | null;
  novelId: string;
  className?: string;
}

/* ------------------------------------------------------------------ */
/*  辅助函数                                                           */
/* ------------------------------------------------------------------ */

/**
 * 2026-04-21，任务：仪表盘组件视觉重构
 * 修改原因：保留叙事结构摘要文案的拼接逻辑，同时配合新的卡片壳展示
 */
function formatEventDensity(density: Record<string, number> | null | undefined): string | null {
  if (!density || Object.keys(density).length === 0) {
    return null;
  }

  const parts = Object.entries(density).map(([key, value]) => {
    const percentage = Math.round(value * 100);
    return `${key}${percentage}%`;
  });

  return `事件密度: ${parts.join(" ")}`;
}

/**
 * 2026-04-21，任务：仪表盘组件视觉重构
 * 修改原因：统一叙事结构卡的数据可用性判断，避免外观重构时误改展示边界
 */
function hasActData(
  act1: number | null | undefined,
  act2: number | null | undefined,
  act3: number | null | undefined
): boolean {
  return act1 != null || act2 != null || act3 != null;
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
  eventDensity,
  novelId,
  className,
}: NarrativeStructureBarProps) {
  const navigate = useNavigate();

  const hasData = hasActData(act1Ratio, act2Ratio, act3Ratio) || eventDensity;

  const segments = hasActData(act1Ratio, act2Ratio, act3Ratio)
    ? [
        {
          label: "引入",
          value: Math.round((act1Ratio ?? 0) * 100),
          colorClass: "bg-chart-1",
        },
        {
          label: "发展",
          value: Math.round((act2Ratio ?? 0) * 100),
          colorClass: "bg-chart-2",
        },
        {
          label: "收束",
          value: Math.round((act3Ratio ?? 0) * 100),
          colorClass: "bg-chart-3",
        },
      ]
    : [];

  const densityText = formatEventDensity(eventDensity);

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
          <>
            {segments.length > 0 && (
              <div className="rounded-2xl border border-border/70 bg-surface/75 p-3.5 shadow-sm">
                <SegmentedBar segments={segments} />
              </div>
            )}

            {densityText ? (
              <p className="rounded-xl border border-chart-1/10 bg-chart-1/5 px-3 py-2.5 text-xs text-text-muted">
                {densityText}
              </p>
            ) : (
              <p className="rounded-xl border border-border/70 bg-surface/70 px-3 py-2.5 text-xs text-text-muted">
                事件密度: 暂无数据
              </p>
            )}
          </>
        ) : (
          <p className="rounded-xl border border-dashed border-border bg-surface/60 px-3 py-2.5 text-xs text-text-muted">
            暂无数据
          </p>
        )}
    </DashboardCardShell>
  );
}
