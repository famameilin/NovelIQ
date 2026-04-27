/**
 * TimelineNode - 时间轴节点组件
 *
 * 创建时间: 2026-04-05
 * 创建者: GLM-5
 * 任务: Phase 2-B 叙事时间轴
 * 说明: 时间轴上的单个节点，根据属性映射大小/颜色/图标
 *
 * 修改时间: 2026-04-21
 * 任务: 修复叙事时间轴页面布局与节点语义表达
 * 修改内容:
 *   - 节点改为显式对齐轨道基线，避免出现节点与时间轴横线错位
 *   - 统一复用节点视觉语义配置，保证图例、节点、详情表达一致
 *   - 增强选中/高亮态，让节点在复杂时间轴中更容易被识别
 */

import { motion } from "framer-motion";
import { cn } from "@/lib/cn";
import type { TimelineNode as TimelineNodeType } from "@/api/types";
import { getTimelineNodePresentation } from "./timelineNodePresentation";

const NODE_SIZE_MIN = 12;
const NODE_SIZE_MAX = 28;

/** 后端 importance_score 最大值（与 timeline.py Field(ge=0, le=13) 对齐） */
const IMPORTANCE_SCORE_MAX = 13;

/* ------------------------------------------------------------------ */
/*  Types                                                             */
/* ------------------------------------------------------------------ */

export interface TimelineNodeProps {
  node: TimelineNodeType;
  isSelected?: boolean;
  isHighlighted?: boolean;
  onClick?: () => void;
  showLabel?: boolean;
  baselineY?: number;
  position?: string;
  verticalOffset?: number;
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
  baselineY = 72,
  position,
  verticalOffset,
}: TimelineNodeProps) {
  const presentation = getTimelineNodePresentation(node.node_type, node.node_subtype);
  const Icon = presentation.icon;

  const size = calculateNodeSize(node.importance_score);
  const resolvedVerticalOffset =
    verticalOffset ?? calculateDefaultVerticalOffset(node.plot_flags?.tension_percentile ?? 50);

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
      onClick={onClick}
      title={node.summary}
      aria-label={`${presentation.label}: ${node.summary}`}
    >
      <div
        className={cn(
          "flex items-center justify-center rounded-full border",
          presentation.dotClassName
        )}
        style={{ width: size, height: size }}
      >
        <Icon
          className={cn(presentation.iconClassName)}
          style={{
            width: size * 0.5,
            height: size * 0.5,
          }}
        />
      </div>

      {showLabel && (
        <span className="absolute top-full mt-1 whitespace-nowrap text-[10px] text-text-muted">
          {(node.summary ?? "").slice(0, 10)}...
        </span>
      )}

      {node.plot_flags?.is_pivot && (
        <span className="absolute -right-1 -top-1 flex h-3 w-3 items-center justify-center rounded-full bg-chart-negative text-[8px] text-white">
          !
        </span>
      )}

      {node.plot_flags?.is_cliffhanger && (
        <span
          className={cn(
            "absolute flex h-3 w-3 items-center justify-center rounded-full bg-chart-3 text-[8px] text-white",
            node.plot_flags?.is_pivot ? "-right-4 -top-1" : "-right-1 -top-1"
          )}
        >
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
  const normalized = Math.min(Math.max(importanceScore, 0), IMPORTANCE_SCORE_MAX);
  const ratio = normalized / IMPORTANCE_SCORE_MAX;
  return NODE_SIZE_MIN + ratio * (NODE_SIZE_MAX - NODE_SIZE_MIN);
}

/**
 * 2026-04-21，任务：重设计叙事时间轴主视觉
 * 新建原因：默认节点仍保留基于张力的轻微偏移，但轨道组件也可以显式覆盖为分层布局偏移。
 */
function calculateDefaultVerticalOffset(tensionPercentile: number): number {
  const normalized = Math.min(Math.max(tensionPercentile, 0), 100);
  const offset = (normalized - 50) * 0.3;
  return -offset;
}
