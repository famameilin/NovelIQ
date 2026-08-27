/**
 * TimelineNode - 事件森林节点徽标（2026-08-20 一树一节点版）
 *
 * 一棵树=一个节点：展示 title||summary 前30字 + character_names + main_chain 长度 + 旁支数
 * 点击回调传递 tree_id，选中态按 tree_id 判
 */

import { motion } from "framer-motion";
import { cn } from "@/lib/cn";
import type { TimelineEventNode } from "@/api/types";
import { getTimelineNodePresentation } from "./timelineNodePresentation";

const NODE_SIZE_MIN = 12;
const NODE_SIZE_MAX = 28;
const IMPORTANCE_SCORE_MAX = 13;

export interface TimelineNodeProps {
  node: TimelineEventNode;
  isSelected?: boolean;
  isHighlighted?: boolean;
  onClick?: (treeId: string) => void;
  showLabel?: boolean;
  baselineY?: number;
  position?: string;
  verticalOffset?: number;
}

function resolveCauseRole(level: 1 | 2 | 3): "root" | "main" | "secondary" {
  if (level === 1) return "root";
  if (level === 2) return "main";
  return "secondary";
}

export function TimelineNode({
  node,
  isSelected,
  isHighlighted,
  onClick,
  showLabel = false,
  baselineY = 72,
  position,
  verticalOffset,
}: TimelineNodeProps) {
  const causeRole = resolveCauseRole(node.level);
  const presentation = getTimelineNodePresentation("event", causeRole);
  const Icon = presentation.icon;

  const size = calculateNodeSize(node.importance_score);
  const resolvedVerticalOffset = verticalOffset ?? 0;
  const displayTitle = (node.title?.trim() ? node.title : node.summary).slice(0, 30);
  const mainChainLen = node.main_chain?.length ?? 0;
  const secondaryCount = node.secondary_groups?.length ?? 0;

  return (
    <motion.button
      className={cn(
        "absolute z-10 flex items-center justify-center rounded-full border border-border/50 bg-background/85 shadow-sm backdrop-blur-sm",
        "cursor-pointer transition-all duration-200",
        "focus:outline-none focus-visible:ring-2 focus-visible:ring-primary",
        isSelected && "ring-2 ring-primary ring-offset-2 ring-offset-surface",
        isHighlighted && !isSelected && "ring-2 ring-chart-4/70 ring-offset-2 ring-offset-surface"
      )}
      style={{
        top: baselineY,
        left: position ?? `${node.progress * 100}%`,
        transform: `translateX(-50%) translateY(-50%) translateY(${resolvedVerticalOffset}px)`,
        width: size,
        height: size,
      }}
      initial={{ scale: 0, opacity: 0 }}
      animate={{ scale: 1, opacity: 1 }}
      transition={{ duration: 0.3, ease: "easeOut" }}
      whileHover={{ scale: 1.2 }}
      onClick={() => onClick?.(node.tree_id)}
      title={node.summary}
      aria-label={`${presentation.label}: ${displayTitle}`}
      data-testid="timeline-node"
      data-tree-id={node.tree_id}
    >
      <div
        className={cn("flex items-center justify-center rounded-full border", presentation.dotClassName)}
        style={{ width: size, height: size }}
      >
        <Icon className={cn(presentation.iconClassName)} style={{ width: size * 0.5, height: size * 0.5 }} />
      </div>

      {showLabel && (
        <span className="absolute top-full mt-1 whitespace-nowrap text-[10px] text-text-muted">
          {displayTitle}
        </span>
      )}

      {/* 角色与链路徽标：主链长度 + 旁支数（按 spec 在节点右上角以 badge 形式） */}
      <span className="absolute -right-1 -top-1 flex min-w-[14px] justify-center rounded-full bg-primary px-1 text-[9px] font-medium text-white">
        {mainChainLen}
      </span>
      {secondaryCount > 0 ? (
        <span className="absolute -right-1 bottom-0 flex min-w-[14px] justify-center rounded-full bg-chart-4 px-1 text-[9px] font-medium text-white">
          +{secondaryCount}
        </span>
      ) : null}

      {/* 角色名气泡（最多展示2个，其余省略） */}
      {node.character_names.length > 0 ? (
        <span className="absolute left-full top-1/2 ml-1 hidden -translate-y-1/2 whitespace-nowrap rounded bg-surface px-1 py-0.5 text-[10px] text-text-muted shadow md:block">
          {node.character_names.slice(0, 2).join(" / ")}
          {node.character_names.length > 2 ? "…" : ""}
        </span>
      ) : null}
    </motion.button>
  );
}

function calculateNodeSize(importanceScore: number): number {
  const normalized = Math.min(Math.max(importanceScore, 0), IMPORTANCE_SCORE_MAX);
  const ratio = normalized / IMPORTANCE_SCORE_MAX;
  return NODE_SIZE_MIN + ratio * (NODE_SIZE_MAX - NODE_SIZE_MIN);
}
