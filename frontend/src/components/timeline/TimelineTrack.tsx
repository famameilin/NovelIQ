/**
 * TimelineTrack - 横向时间轴轨道组件
 *
 * 创建时间: 2026-04-05
 * 创建者: GLM-5
 * 任务: Phase 2-B 叙事时间轴
 * 说明: 横向时间轴轨道，包含节点和连接线
 */

import { motion } from "framer-motion";
import { useRef } from "react";
import { cn } from "@/lib/cn";
import type { TimelineNode as TimelineNodeType } from "@/api/types";
import { TimelineNode } from "./TimelineNode";

/* ------------------------------------------------------------------ */
/*  Types                                                             */
/* ------------------------------------------------------------------ */

export interface TimelineTrackProps {
  nodes: TimelineNodeType[];
  selectedNodeId?: number;
  onNodeClick?: (node: TimelineNodeType) => void;
  className?: string;
}

/* ------------------------------------------------------------------ */
/*  Component                                                         */
/* ------------------------------------------------------------------ */

export function TimelineTrack({
  nodes,
  selectedNodeId,
  onNodeClick,
  className,
}: TimelineTrackProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  const sortedNodes = [...nodes].sort((a, b) => a.progress - b.progress);

  return (
    <div ref={containerRef} className={cn("relative", className)}>
      <div className="relative h-24 w-full">
        <div className="absolute left-0 right-0 top-1/2 h-0.5 -translate-y-1/2 bg-border" />

        {sortedNodes.length > 1 && (
          <svg
            className="absolute left-0 top-0 h-full w-full overflow-visible"
            style={{ pointerEvents: "none" }}
          >
            {sortedNodes.slice(0, -1).map((node, i) => {
              const nextNode = sortedNodes[i + 1];
              const x1 = `${node.progress * 100}%`;
              const x2 = `${nextNode.progress * 100}%`;
              return (
                <motion.line
                  key={`line-${node.chunk_id}`}
                  x1={x1}
                  y1="50%"
                  x2={x2}
                  y2="50%"
                  stroke="var(--border)"
                  strokeWidth="1"
                  strokeDasharray="4 2"
                  initial={{ pathLength: 0 }}
                  animate={{ pathLength: 1 }}
                  transition={{ duration: 0.5, delay: i * 0.05 }}
                />
              );
            })}
          </svg>
        )}

        {sortedNodes.map((node) => (
          <TimelineNode
            key={node.chunk_id}
            node={node}
            isSelected={selectedNodeId === node.chunk_id}
            onClick={() => onNodeClick?.(node)}
          />
        ))}
      </div>

      {sortedNodes.length === 0 && (
        <div className="flex h-24 items-center justify-center text-sm text-text-muted">
          暂无时间轴节点
        </div>
      )}
    </div>
  );
}
