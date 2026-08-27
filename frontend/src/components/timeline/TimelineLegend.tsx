/**
 * TimelineLegend - 时间轴图例组件
 *
 * 明确节点颜色、尺寸和状态标记的含义，降低“只看颜色完全不知道是什么意思”的理解成本
 *
 *   - 由大块卡片改为紧凑图例行，减少视觉噪音
 *   - 补充“节点越大、越重要”等阅读提示，服务时间轴主视图
 */

import { cn } from "@/lib/cn";
import { getTimelineNodePresentation } from "./timelineNodePresentation";

export interface TimelineLegendProps {
  className?: string;
}

export function TimelineLegend({ className }: TimelineLegendProps) {
  // 一树一节点体系：仅展示根因 / 主链 / 旁支 三档 + 因果边图例
  const presentations = [
    { key: "root", nodeType: "event" as const, nodeSubtype: "root" },
    { key: "main", nodeType: "event" as const, nodeSubtype: "main" },
    { key: "secondary", nodeType: "event" as const, nodeSubtype: "secondary" },
  ] as const;

  return (
    <div className={cn("flex flex-wrap items-center gap-2", className)}>
      {presentations.map(({ key, nodeType, nodeSubtype }) => {
        const presentation = getTimelineNodePresentation(nodeType, nodeSubtype);
        const Icon = presentation.icon;
        return (
          <div
            key={key}
            data-testid={`legend-${key}`}
            className="inline-flex items-center gap-2 rounded-full border border-border/60 bg-background/70 px-3 py-1.5"
            title={presentation.description}
          >
            <div
              className={cn(
                "flex h-7 w-7 shrink-0 items-center justify-center rounded-full border",
                presentation.dotClassName
              )}
            >
              <Icon className={cn("h-3.5 w-3.5", presentation.iconClassName)} />
            </div>
            <span className="text-xs font-medium text-text">{presentation.label}</span>
          </div>
        );
      })}
      {/* 因果边图例：实线=active 虚线=inactive，与详情因果区块灰显一致 */}
      <div
        data-testid="legend-causal-active"
        className="inline-flex items-center gap-2 rounded-full border border-border/60 bg-background/70 px-3 py-1.5"
        title="实线为活跃因果边"
      >
        <span className="h-0.5 w-8 bg-primary" />
        <span className="text-xs font-medium text-text">因果（活跃）</span>
      </div>
      <div
        data-testid="legend-causal-inactive"
        className="inline-flex items-center gap-2 rounded-full border border-border/60 bg-background/70 px-3 py-1.5 opacity-70"
        title="虚线为已失效因果边，详情中灰显"
      >
        <span className="h-0.5 w-8 border-t border-dashed border-text-muted bg-transparent" />
        <span className="text-xs font-medium text-text-muted">因果（已失效）</span>
      </div>
    </div>
  );
}
