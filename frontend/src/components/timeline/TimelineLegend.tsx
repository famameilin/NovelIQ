/**
 * TimelineLegend - 时间轴图例组件
 *
 * 创建时间: 2026-04-21
 * 任务: 修复叙事时间轴页面布局与节点语义表达
 * 说明: 明确节点颜色、尺寸和状态标记的含义，降低“只看颜色完全不知道是什么意思”的理解成本。
 *
 * 修改时间: 2026-04-21
 * 任务: 重设计叙事时间轴主视觉
 * 修改内容:
 *   - 由大块卡片改为紧凑图例行，减少视觉噪音
 *   - 补充“节点越大、越重要”等阅读提示，服务时间轴主视图
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
        "flex flex-wrap items-center gap-2",
        className
      )}
    >
      {Object.entries(TIMELINE_NODE_PRESENTATIONS).map(([nodeType, presentation]) => {
        const Icon = presentation.icon;
        const semanticPresentation = getTimelineNodePresentation(nodeType);
        return (
          <div
            key={nodeType}
            className="inline-flex items-center gap-2 rounded-full border border-border/60 bg-background/70 px-3 py-1.5"
            title={presentation.description}
          >
            <div
              className={cn(
                "flex h-7 w-7 shrink-0 items-center justify-center rounded-full border",
                semanticPresentation.dotClassName
              )}
            >
              <Icon className={cn("h-3.5 w-3.5", semanticPresentation.iconClassName)} />
            </div>
            <span className="text-xs font-medium text-text">{presentation.label}</span>
          </div>
        );
      })}
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
        上下分层帮助阅读密集节点
      </Badge>
    </div>
  );
}
