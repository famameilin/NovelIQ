/**
 * timelineNodePresentation - 时间轴节点视觉语义配置
 *
 * 创建时间: 2026-04-21
 * 任务: 修复叙事时间轴页面布局与节点语义表达
 * 说明: 统一维护节点类型的图标、颜色、文案，避免时间轴、图例、详情面板各自维护一套含义。
 *
 * 修改时间: 2026-04-27
 * 任务: 时间轴合同重构
 * 修改内容:
 *   - 改为 node_type + node_subtype 双层语义
 *   - lifecycle 的 entry / exit 与 relation 的不同变化类型统一走同一选择器
 */

import { Link2, User, UserMinus, Zap, type LucideIcon } from "lucide-react";

export interface TimelineNodePresentation {
  icon: LucideIcon;
  label: string;
  description: string;
  dotClassName: string;
  iconClassName: string;
  accent: "primary" | "chart-2" | "chart-3" | "chart-5";
}

const DEFAULT_PLOT_PRESENTATION: TimelineNodePresentation = {
  icon: Zap,
  label: "剧情节点",
  description: "关键剧情推进、转折或节奏抬升节点",
  dotClassName: "border-primary/30 bg-primary/15",
  iconClassName: "text-primary",
  accent: "primary",
};

const PRESENTATION_MAP: Record<string, TimelineNodePresentation> = {
  plot: DEFAULT_PLOT_PRESENTATION,
  relation: {
    icon: Link2,
    label: "关系变化",
    description: "角色关系发生了可进入图谱历史的真实变化",
    dotClassName: "border-chart-2/30 bg-chart-2/15",
    iconClassName: "text-chart-2",
    accent: "chart-2",
  },
  "lifecycle:entry": {
    icon: User,
    label: "角色登场",
    description: "角色首次进入稳定叙事舞台",
    dotClassName: "border-chart-positive/30 bg-chart-positive/15",
    iconClassName: "text-chart-positive",
    accent: "chart-3",
  },
  "lifecycle:exit": {
    icon: UserMinus,
    label: "角色退场",
    description: "角色从稳定活跃状态中退出",
    dotClassName: "border-chart-negative/30 bg-chart-negative/15",
    iconClassName: "text-chart-negative",
    accent: "chart-5",
  },
};

/**
 * 2026-04-27，任务：时间轴合同重构
 * 新建原因：节点视觉语义现在由 node_type/node_subtype 共同决定，
 * 必须避免前端继续把 lifecycle 与 relation 节点硬压回旧的单字符串类型。
 */
export function getTimelineNodePresentation(
  nodeType: "plot" | "relation" | "lifecycle",
  nodeSubtype: string,
): TimelineNodePresentation {
  if (nodeType === "lifecycle") {
    return PRESENTATION_MAP[`lifecycle:${nodeSubtype}`] ?? DEFAULT_PLOT_PRESENTATION;
  }
  return PRESENTATION_MAP[nodeType] ?? DEFAULT_PLOT_PRESENTATION;
}
