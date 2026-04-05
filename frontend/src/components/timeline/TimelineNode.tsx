/**
 * TimelineNode - 时间轴节点组件
 *
 * 创建时间: 2026-04-05
 * 创建者: GLM-5
 * 任务: Phase 2-B 叙事时间轴
 * 说明: 时间轴上的单个节点，根据属性映射大小/颜色/图标
 */

import { motion } from "framer-motion";
import {
  Zap,
  User,
  UserMinus,
  Link2,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/cn";
import type { TimelineNode as TimelineNodeType } from "@/api/types";

/* ------------------------------------------------------------------ */
/*  Constants                                                         */
/* ------------------------------------------------------------------ */

const NODE_TYPE_CONFIG: Record<
  string,
  { icon: LucideIcon; bgClass: string; textClass: string; label: string }
> = {
  plot: { icon: Zap, bgClass: "bg-primary", textClass: "text-primary", label: "情节" },
  character_entry: {
    icon: User,
    bgClass: "bg-chart-positive",
    textClass: "text-chart-positive",
    label: "角色登场",
  },
  character_exit: {
    icon: UserMinus,
    bgClass: "bg-chart-negative",
    textClass: "text-chart-negative",
    label: "角色退场",
  },
  relation_change: {
    icon: Link2,
    bgClass: "bg-chart-2",
    textClass: "text-chart-2",
    label: "关系变化",
  },
};

const NODE_SIZE_MIN = 12;
const NODE_SIZE_MAX = 28;

/* ------------------------------------------------------------------ */
/*  Types                                                             */
/* ------------------------------------------------------------------ */

export interface TimelineNodeProps {
  node: TimelineNodeType;
  isSelected?: boolean;
  isHighlighted?: boolean;
  onClick?: () => void;
  showLabel?: boolean;
}

/* ------------------------------------------------------------------ */
/*  Component                                                         */
/* ------------------------------------------------------------------ */

export function TimelineNode({
  node,
  isSelected,
  isHighlighted,
  onClick,
  showLabel = false,
}: TimelineNodeProps) {
  const config = NODE_TYPE_CONFIG[node.node_type] || NODE_TYPE_CONFIG.plot;
  const Icon = config.icon;

  const size = calculateNodeSize(node.importance_score);
  const verticalOffset = calculateVerticalOffset(node.tension_percentile);

  return (
    <motion.button
      className={cn(
        "absolute flex items-center justify-center rounded-full",
        "transition-all duration-200 cursor-pointer",
        "focus:outline-none focus-visible:ring-2 focus-visible:ring-primary",
        isSelected && "ring-2 ring-primary ring-offset-2"
      )}
      style={{
        left: `${node.progress * 100}%`,
        transform: `translateX(-50%) translateY(${verticalOffset}px)`,
        width: size,
        height: size,
      }}
      initial={{ scale: 0, opacity: 0 }}
      animate={{ scale: 1, opacity: 1 }}
      transition={{ duration: 0.3, ease: "easeOut" }}
      whileHover={{ scale: 1.2 }}
      onClick={onClick}
      title={node.event}
    >
      <div
        className={cn(
          "flex items-center justify-center rounded-full",
          "bg-opacity-20",
          config.bgClass,
          isHighlighted && "ring-2 ring-offset-1 ring-chart-4"
        )}
        style={{ width: size, height: size }}
      >
        <Icon
          className={cn(config.textClass)}
          style={{
            width: size * 0.5,
            height: size * 0.5,
          }}
        />
      </div>

      {showLabel && (
        <span className="absolute top-full mt-1 whitespace-nowrap text-[10px] text-text-muted">
          {node.event.slice(0, 10)}...
        </span>
      )}

      {node.is_pivot && (
        <span className="absolute -right-1 -top-1 flex h-3 w-3 items-center justify-center rounded-full bg-chart-negative text-[8px] text-white">
          !
        </span>
      )}

      {node.is_cliffhanger && (
        <span className="absolute -right-1 -top-1 flex h-3 w-3 items-center justify-center rounded-full bg-chart-3 text-[8px] text-white">
          ?
        </span>
      )}
    </motion.button>
  );
}

/* ------------------------------------------------------------------ */
/*  Helper Functions                                                  */
/* ------------------------------------------------------------------ */

function calculateNodeSize(importanceScore: number): number {
  const normalized = Math.min(Math.max(importanceScore, 0), 13);
  const ratio = normalized / 13;
  return NODE_SIZE_MIN + ratio * (NODE_SIZE_MAX - NODE_SIZE_MIN);
}

function calculateVerticalOffset(tensionPercentile: number): number {
  const normalized = Math.min(Math.max(tensionPercentile, 0), 100);
  const offset = (normalized - 50) * 0.3;
  return -offset;
}
