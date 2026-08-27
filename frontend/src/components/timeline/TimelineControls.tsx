/**
 * TimelineControls - 时间轴控制面板组件（2026-08-20 事件森林版）
 *
 * 一树一节点体系下仅保留重要性级别筛选，移除 composite/atomic 视图切换
 * `maxLevel` 仅表示前端本地展示层级，按 importance_score/level 统一过滤
 */

import { cn } from "@/lib/cn";
import { Button } from "@/components/ui/button";
import { Filter } from "lucide-react";

/* ------------------------------------------------------------------ */
/*  类型定义                                                           */
/* ------------------------------------------------------------------ */

export interface TimelineControlsProps {
  maxLevel: 1 | 2 | 3;
  onMaxLevelChange: (level: 1 | 2 | 3) => void;
  className?: string;
  variant?: "card" | "inline";
  /** @deprecated 事件森林体系已移除视图切换，保留仅为兼容旧调用 */
  viewMode?: "composite" | "atomic";
  /** @deprecated */
  onViewModeChange?: (viewMode: "composite" | "atomic") => void;
}

/* ------------------------------------------------------------------ */
/*  常量                                                               */
/* ------------------------------------------------------------------ */

const LEVEL_CONFIG: Record<
  number,
  { label: string; description: string }
> = {
  1: { label: "重要", description: "仅显示重要节点" },
  2: { label: "较重要", description: "显示重要+较重要节点" },
  3: { label: "全部", description: "显示全部节点" },
};

/* ------------------------------------------------------------------ */
/*  组件主体                                                           */
/* ------------------------------------------------------------------ */

export function TimelineControls({
  maxLevel,
  onMaxLevelChange,
  className,
  variant = "card",
}: TimelineControlsProps) {
  const content = (
    <div
      className={cn(
        "flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-border/60 bg-surface/70 px-4 py-3",
        variant === "inline" && "border-border/50 bg-background/70 px-3 py-2"
      )}
    >
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2">
          <Filter className="h-4 w-4 text-text-muted" />
          <span className="text-sm font-medium text-text">节点筛选</span>
        </div>
        <div className="flex gap-1">
          {([1, 2, 3] as const).map((level) => {
            const config = LEVEL_CONFIG[level];
            const isActive = maxLevel === level;
            return (
              <Button
                key={level}
                variant={isActive ? "default" : "outline"}
                size="sm"
                onClick={() => onMaxLevelChange(level)}
                className={cn(
                  "h-7 px-3 text-xs",
                  isActive && "bg-primary text-primary-foreground"
                )}
                title={config.description}
              >
                {config.label}
              </Button>
            );
          })}
        </div>
      </div>
      <span className="text-xs text-text-muted">按重要度筛选（level ≤ {maxLevel}）</span>
    </div>
  );

  if (variant === "inline") {
    return <div className={cn(className)}>{content}</div>;
  }

  return <div className={cn(className)}>{content}</div>;
}
