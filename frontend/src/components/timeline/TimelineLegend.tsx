/**
 * TimelineLegend - 时间轴图例组件
 *
 * 创建时间: 2026-04-21
 * 任务: 修复叙事时间轴页面布局与节点语义表达
 * 说明: 明确节点颜色、尺寸和状态标记的含义，降低“只看颜色完全不知道是什么意思”的理解成本。
 */

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/cn";
import { getTimelineNodePresentation, TIMELINE_NODE_PRESENTATIONS } from "./timelineNodePresentation";

export interface TimelineLegendProps {
  className?: string;
}

export function TimelineLegend({ className }: TimelineLegendProps) {
  return (
    <div
      className={cn(
        "rounded-2xl border border-border/60 bg-surface/70 p-4",
        className
      )}
    >
      <div className="flex flex-wrap gap-2.5">
        {Object.entries(TIMELINE_NODE_PRESENTATIONS).map(([nodeType, presentation]) => {
          const Icon = presentation.icon;
          const semanticPresentation = getTimelineNodePresentation(nodeType);
          return (
            <div
              key={nodeType}
              className="flex min-w-[220px] flex-1 items-start gap-3 rounded-xl border border-border/50 bg-background/60 px-3 py-3"
            >
              <div
                className={cn(
                  "flex h-10 w-10 shrink-0 items-center justify-center rounded-full border shadow-sm",
                  semanticPresentation.dotClassName
                )}
              >
                <Icon className={cn("h-4 w-4", semanticPresentation.iconClassName)} />
              </div>
              <div className="min-w-0">
                <p className="text-sm font-medium text-text">{presentation.label}</p>
                <p className="mt-1 text-xs leading-5 text-text-muted">{presentation.description}</p>
              </div>
            </div>
          );
        })}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Badge variant="outline" className="gap-1 border-chart-negative/30 text-chart-negative">
          <span className="text-[10px] font-bold">!</span>
          转折点
        </Badge>
        <Badge variant="outline" className="gap-1 border-chart-3/30 text-chart-3">
          <span className="text-[10px] font-bold">?</span>
          悬念点
        </Badge>
        <Badge variant="outline" className="text-text-muted">
          节点越大，重要性越高
        </Badge>
        <Badge variant="outline" className="text-text-muted">
          节点上下起伏与下方张力曲线同向
        </Badge>
      </div>
    </div>
  );
}
