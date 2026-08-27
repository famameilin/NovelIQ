/**
 * timelineNodePresentation - 时间轴节点视觉语义配置
 *
 * 统一维护节点类型的图标、颜色、文案，避免时间轴、图例、详情面板各自维护一套含义
 *
 *   - 改为 node_type + node_subtype 双层语义
 *   - lifecycle 的 entry / exit 与 relation 的不同变化类型统一走同一选择器
 */

import { Activity, Link2, Zap, type LucideIcon } from "lucide-react";

export interface TimelineNodePresentation {
  icon: LucideIcon;
  label: string;
  description: string;
  dotClassName: string;
  iconClassName: string;
  accent: "primary" | "chart-2" | "chart-3" | "chart-4" | "chart-5";
}

const DEFAULT_EVENT_PRESENTATION: TimelineNodePresentation = {
  icon: Zap,
  label: "完整事件",
  description: "事件森林一树一节点完整视图",
  dotClassName: "border-primary/30 bg-primary/15",
  iconClassName: "text-primary",
  accent: "primary",
};

const PRESENTATION_MAP: Record<string, TimelineNodePresentation> = {
  "event:root": {
    icon: Zap,
    label: "根因事件",
    description: "事件森林根因节点：该树的因果起点",
    dotClassName: "border-primary/30 bg-primary/15",
    iconClassName: "text-primary",
    accent: "primary",
  },
  "event:main": {
    icon: Link2,
    label: "主链事件",
    description: "主链事件：沿根因展开的核心因果链条",
    dotClassName: "border-chart-2/30 bg-chart-2/15",
    iconClassName: "text-chart-2",
    accent: "chart-2",
  },
  "event:secondary": {
    icon: Activity,
    label: "旁支事件",
    description: "旁支事件：次因分支扩散",
    dotClassName: "border-chart-4/30 bg-chart-4/15",
    iconClassName: "text-chart-4",
    accent: "chart-4",
  },
  event: {
    icon: Zap,
    label: "完整事件",
    description: "事件森林一树一节点",
    dotClassName: "border-primary/30 bg-primary/15",
    iconClassName: "text-primary",
    accent: "primary",
  },
};

export function getTimelineNodePresentation(
  _nodeType: "event",
  nodeSubtype: string,
): TimelineNodePresentation {
  return PRESENTATION_MAP[`event:${nodeSubtype}`] ?? PRESENTATION_MAP["event"] ?? DEFAULT_EVENT_PRESENTATION;
}
