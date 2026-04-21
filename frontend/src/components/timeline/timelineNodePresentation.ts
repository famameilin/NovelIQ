/**
 * timelineNodePresentation - 时间轴节点视觉语义配置
 *
 * 创建时间: 2026-04-21
 * 任务: 修复叙事时间轴页面布局与节点语义表达
 * 说明: 统一维护节点类型的图标、颜色、文案，避免时间轴、图例、详情面板各自维护一套含义。
 */

import {
  Link2,
  User,
  UserMinus,
  Zap,
  type LucideIcon,
} from "lucide-react";

export interface TimelineNodePresentation {
  icon: LucideIcon;
  label: string;
  description: string;
  dotClassName: string;
  iconClassName: string;
  accent: "primary" | "chart-2" | "chart-3" | "chart-5";
}

export const TIMELINE_NODE_PRESENTATIONS: Record<string, TimelineNodePresentation> = {
  plot: {
    icon: Zap,
    label: "情节推进",
    description: "关键剧情推进或转折事件",
    dotClassName: "border-primary/30 bg-primary/15",
    iconClassName: "text-primary",
    accent: "primary",
  },
  character_entry: {
    icon: User,
    label: "角色登场",
    description: "角色首次进入稳定叙事舞台",
    dotClassName: "border-chart-positive/30 bg-chart-positive/15",
    iconClassName: "text-chart-positive",
    accent: "chart-3",
  },
  character_exit: {
    icon: UserMinus,
    label: "角色退场",
    description: "角色从稳定活跃状态中退出",
    dotClassName: "border-chart-negative/30 bg-chart-negative/15",
    iconClassName: "text-chart-negative",
    accent: "chart-5",
  },
  relation_change: {
    icon: Link2,
    label: "关系变化",
    description: "人物关系在该叙事块发生显著变化",
    dotClassName: "border-chart-2/30 bg-chart-2/15",
    iconClassName: "text-chart-2",
    accent: "chart-2",
  },
};

/**
 * 2026-04-21，任务：修复叙事时间轴页面布局与节点语义表达
 * 新建原因：让页面上的图例、节点与详情面板使用同一套类型语义，避免颜色含义不一致。
 */
export function getTimelineNodePresentation(nodeType: string): TimelineNodePresentation {
  return TIMELINE_NODE_PRESENTATIONS[nodeType] ?? TIMELINE_NODE_PRESENTATIONS.plot;
}
