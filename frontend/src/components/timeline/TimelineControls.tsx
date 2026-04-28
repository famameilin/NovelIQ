/**
 * TimelineControls - 时间轴控制面板组件
 *
 * 提供重要性级别筛选
 *
 *   - 支持内联模式，便于直接嵌入时间轴主图顶部而不是额外挂一个控制卡片
 *
 *   - 增加复合视图 / 原子视图切换
 *   - `maxLevel` 仅表示前端本地展示层级，不再表示后端裁剪参数
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
  viewMode: "composite" | "atomic";
  onViewModeChange: (viewMode: "composite" | "atomic") => void;
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
  viewMode,
  onViewModeChange,
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
      <div className="flex items-center gap-1">
        <Button
          variant={viewMode === "composite" ? "default" : "outline"}
          size="sm"
          onClick={() => onViewModeChange("composite")}
          className={cn("h-7 px-3 text-xs", viewMode === "composite" && "bg-primary text-primary-foreground")}
          title="默认概览视图"
        >
          复合视图
        </Button>
        <Button
          variant={viewMode === "atomic" ? "default" : "outline"}
          size="sm"
          onClick={() => onViewModeChange("atomic")}
          className={cn("h-7 px-3 text-xs", viewMode === "atomic" && "bg-primary text-primary-foreground")}
          title="查看全部原子节点"
        >
          原子视图
        </Button>
      </div>
    </div>
  );

  if (variant === "inline") {
    return <div className={cn(className)}>{content}</div>;
  }

  return <div className={cn(className)}>{content}</div>;
}
