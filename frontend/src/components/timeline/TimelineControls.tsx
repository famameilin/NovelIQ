/**
 * TimelineControls - 时间轴控制面板组件
 *
 * 创建时间: 2026-04-05
 * 创建者: GLM-5
 * 任务: Phase 2-B 叙事时间轴
 * 说明: 提供重要性级别筛选和张力曲线显隐开关
 */

import { cn } from "@/lib/cn";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Eye, EyeOff, Filter } from "lucide-react";

/* ------------------------------------------------------------------ */
/*  Types                                                             */
/* ------------------------------------------------------------------ */

export interface TimelineControlsProps {
  maxLevel: 1 | 2 | 3;
  showTension: boolean;
  onMaxLevelChange: (level: 1 | 2 | 3) => void;
  onShowTensionChange: (show: boolean) => void;
  className?: string;
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
  showTension,
  onMaxLevelChange,
  onShowTensionChange,
  className,
}: TimelineControlsProps) {
  return (
    <Card variant="elevated" className={cn("rounded-xl", className)}>
      <CardContent className="flex flex-wrap items-center justify-between gap-4 py-3">
        <div className="flex items-center gap-2">
          <Filter className="h-4 w-4 text-text-muted" />
          <span className="text-sm font-medium text-text">节点筛选</span>
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

        <div className="flex items-center gap-2">
          <span className="text-sm text-text-muted">张力曲线</span>
          <Button
            variant="outline"
            size="sm"
            onClick={() => onShowTensionChange(!showTension)}
            className={cn(
              "h-7 gap-1.5 px-3 text-xs",
              showTension && "border-primary text-primary"
            )}
          >
            {showTension ? (
              <>
                <Eye className="h-3.5 w-3.5" />
                显示
              </>
            ) : (
              <>
                <EyeOff className="h-3.5 w-3.5" />
                隐藏
              </>
            )}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
