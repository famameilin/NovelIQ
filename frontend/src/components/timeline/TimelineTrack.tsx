/**
 * TimelineTrack - 横向时间轴轨道组件
 *
 * 创建时间: 2026-04-05
 * 创建者: GLM-5
 * 任务: Phase 2-B 叙事时间轴
 * 说明: 横向时间轴轨道，包含节点和连接线
 *
 * 修改时间: 2026-04-21
 * 任务: 修复叙事时间轴页面布局与节点语义表达
 * 修改内容:
 *   - 为首尾节点增加安全边距，避免节点被容器裁切
 *   - 显式定义时间轴基线与画布高度，消除节点漂浮/错位
 *   - 为窄屏提供横向滚动与最小宽度，减少节点拥挤重叠
 */

import { motion } from "framer-motion";
import { useRef, useMemo, useCallback } from "react";
import { cn } from "@/lib/cn";
import type { TimelineNode as TimelineNodeType } from "@/api/types";
import { TimelineNode } from "./TimelineNode";

/* ------------------------------------------------------------------ */
/*  Types                                                             */
/* ------------------------------------------------------------------ */

export interface TimelineTrackProps {
  nodes: TimelineNodeType[];
  phases?: { name: string; start: number; end: number; ratio: number }[];
  activePhase?: string;
  selectedNodeId?: number;
  onNodeClick?: (node: TimelineNodeType) => void;
  className?: string;
}

/* ------------------------------------------------------------------ */
/*  Component                                                         */
/* ------------------------------------------------------------------ */

const TRACK_SIDE_PADDING_PX = 28;
const TRACK_BASELINE_Y = 72;
const TRACK_HEIGHT_PX = 160;
const TRACK_MIN_WIDTH_PX = 720;
const TRACK_NODE_SPACING_PX = 84;

export function TimelineTrack({
  nodes,
  phases,
  activePhase,
  selectedNodeId,
  onNodeClick,
  className,
}: TimelineTrackProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  // 预计算当前激活阶段的 chunk 范围，用于节点高亮
  const highlightedRange = useMemo(() => {
    if (!activePhase || !phases) return null;
    const phase = phases.find((p) => p.name === activePhase);
    return phase ? [phase.start, phase.end] as [number, number] : null;
  }, [activePhase, phases]);

  // 判断某个节点是否属于高亮阶段（useCallback 避免每次 render 重创建）
  const isNodeInHighlight = useCallback(
    (node: TimelineNodeType): boolean => {
      if (!highlightedRange) return false;
      return node.chunk_id >= highlightedRange[0] && node.chunk_id <= highlightedRange[1];
    },
    [highlightedRange]
  );

  const sortedNodes = useMemo(
    () => [...(nodes || [])].sort((a, b) => a.progress - b.progress),
    [nodes]
  );

  const canvasMinWidth = useMemo(() => {
    return Math.max(TRACK_MIN_WIDTH_PX, sortedNodes.length * TRACK_NODE_SPACING_PX);
  }, [sortedNodes.length]);

  return (
    <div ref={containerRef} className={cn("relative overflow-x-auto pb-2", className)}>
      <div className="relative mx-auto" style={{ minWidth: `${canvasMinWidth}px` }}>
        <div
          className="relative"
          style={{ height: `${TRACK_HEIGHT_PX}px` }}
        >
          <div
            className="absolute h-0.5 rounded-full bg-border"
            style={{
              top: `${TRACK_BASELINE_Y}px`,
              left: `${TRACK_SIDE_PADDING_PX}px`,
              right: `${TRACK_SIDE_PADDING_PX}px`,
            }}
          />

          {sortedNodes.length > 1 &&
            sortedNodes.slice(0, -1).map((node, i) => {
              const nextNode = sortedNodes[i + 1];
              const x1 = getTrackPosition(node.progress);
              const x2 = getTrackPosition(nextNode.progress);
              return (
                <motion.div
                  key={`line-${node.chunk_id}`}
                  className="absolute h-px origin-left bg-border"
                  style={{
                    top: `${TRACK_BASELINE_Y}px`,
                    left: x1,
                    width: `calc(${x2} - ${x1})`,
                  }}
                  initial={{ scaleX: 0, opacity: 0.3 }}
                  animate={{ scaleX: 1, opacity: 1 }}
                  transition={{ duration: 0.4, delay: i * 0.05 }}
                />
              );
            })}

          {sortedNodes.map((node) => (
            <TimelineNode
              key={node.chunk_id}
              node={node}
              baselineY={TRACK_BASELINE_Y}
              position={getTrackPosition(node.progress)}
              isSelected={selectedNodeId === node.chunk_id}
              isHighlighted={isNodeInHighlight(node)}
              onClick={() => onNodeClick?.(node)}
            />
          ))}
        </div>

        <div className="mt-3 flex items-center justify-between px-1 text-xs text-text-muted">
          <span>开篇</span>
          <span>叙事推进</span>
          <span>结尾</span>
        </div>

        {sortedNodes.length === 0 && (
          <div
            className="flex items-center justify-center text-sm text-text-muted"
            style={{ height: `${TRACK_HEIGHT_PX}px` }}
          >
            暂无时间轴节点
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * 2026-04-21，任务：修复叙事时间轴页面布局与节点语义表达
 * 新建原因：首尾节点需要安全边距，不能直接把节点中心点贴到 0% 或 100% 的容器边缘。
 */
function getTrackPosition(progress: number): string {
  const normalized = Math.min(Math.max(progress, 0), 1);
  return `calc(${TRACK_SIDE_PADDING_PX}px + ${normalized} * (100% - ${TRACK_SIDE_PADDING_PX * 2}px))`;
}
