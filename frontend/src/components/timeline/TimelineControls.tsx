/**
 * TimelineControls - 时间轴控制面板组件
 *
 * 创建时间: 2026-04-05
 * 创建者: GLM-5
 * 任务: Phase 2-B 叙事时间轴
 * 说明: 提供重要性级别筛选
 *
 * 修改时间: 2026-04-21
 * 任务: 重设计叙事时间轴主视觉
 * 修改内容:
 *   - 支持内联模式，便于直接嵌入时间轴主图顶部而不是额外挂一个控制卡片
 */

import { cn } from "@/lib/cn";
import { Button } from "@/components/ui/button";
import { Filter } from "lucide-react";

/* ------------------------------------------------------------------ */
/*  Types                                                             */
/* ------------------------------------------------------------------ */

export interface TimelineControlsProps {
  maxLevel: 1 | 2 | 3;
  onMaxLevelChange: (level: 1 | 2 | 3) => void;
  className?: string;
  variant?: "card" | "inline";
}

/* ------------------------------------------------------------------ */
/*  Constants                                                         */
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
/*  Component                                                         */
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
        variant === "inline" && "border-border/50 bg-background/70 px-3 py-2.5"
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

    </div>
  );

  if (variant === "inline") {
    return <div className={cn(className)}>{content}</div>;
  }

  return <div className={cn(className)}>{content}</div>;
}
