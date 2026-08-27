/**
 * TimelineTrack - 叙事时间轴主视图组件（2026-08-20 事件森林版）
 *
 * - 一棵树=一个节点，按 derived_event_order 均匀排布
 * - anchorX 均匀分布 + 最小间距微调，anchorY 仍按 progress 插值张力曲线
 * - 支持跨章区间半透明带宽条
 */

import { motion } from "framer-motion";
import { useCallback, useMemo } from "react";

import type { TimelineEventNode, TimelinePhase } from "@/api/types";
import { cn } from "@/lib/cn";

import {
  calculateCanvasMinWidth,
  createTimelineLayoutNodes,
  getEventSpanWidth,
  getLabelTopPx,
  LABEL_HEIGHT_PX,
  PHASE_BAND_BOTTOM_PX,
  PHASE_BAND_TOP_PX,
  TRACK_NODE_END_PADDING_PX,
  TRACK_NODE_START_PADDING_PX,
} from "./timelineTrackLayout";
import { getTimelineNodePresentation } from "./timelineNodePresentation";
import { buildTensionAreaPath, getTrackPositionPx, TRACK_HEIGHT_PX } from "./timelineTrackPaths";

export type TimelineDisplayNode = TimelineEventNode;

type TimelineTrackNodeInput = TimelineEventNode;

export interface TimelineTrackProps {
  nodes: TimelineTrackNodeInput[];
  derivedOrder?: string[];
  phases?: { name: string; start: number; end: number; ratio: number }[] | TimelinePhase[];
  activePhase?: string;
  selectedNodeId?: string;
  onNodeClick?: (node: TimelineEventNode) => void;
  className?: string;
  tensionCurve?: number[] | null;
  totalChapters?: number;
}

const PHASE_SURFACE_CLASS_MAP: Record<string, string> = {
  引入期: "from-chart-1/12 to-chart-1/4",
  发展期: "from-chart-2/12 to-chart-2/4",
  高潮期: "from-chart-3/12 to-chart-3/4",
  收束期: "from-chart-4/12 to-chart-4/4",
};

function isTimelineEventNode(node: TimelineTrackNodeInput): node is TimelineEventNode {
  return typeof (node as TimelineEventNode).tree_id === "string" && typeof (node as TimelineEventNode).root_event_id === "string";
}

function resolveNodeKey(node: TimelineTrackNodeInput): string {
  // 类型守卫确保为 TimelineEventNode，避免 any 逃逸
  if (isTimelineEventNode(node)) {
    return node.root_event_id ?? node.tree_id ?? "";
  }
  return (node as TimelineEventNode).tree_id ?? "";
}

function resolveChapterIds(node: TimelineTrackNodeInput): number[] {
  if (Array.isArray(node.chapter_ids) && node.chapter_ids.length > 0) return node.chapter_ids;
  return typeof node.anchor_chapter_id === "number" ? [node.anchor_chapter_id] : [];
}

function getEventPresentationSubtype(node: TimelineTrackNodeInput): string {
  if (node.level === 1) return "root";
  if (node.level === 2) return "main";
  if (node.level === 3) return "secondary";
  return "root";
}

export function TimelineTrack({
  nodes,
  derivedOrder = [],
  phases,
  activePhase,
  selectedNodeId,
  onNodeClick,
  className,
  tensionCurve,
  totalChapters = 0,
}: TimelineTrackProps) {
  const highlightedRange = useMemo(() => {
    if (!activePhase || !phases) return null;
    const phase = phases.find((item) => item.name === activePhase);
    return phase ? ([phase.start, phase.end] as [number, number]) : null;
  }, [activePhase, phases]);

  const isNodeInHighlight = useCallback(
    (node: TimelineTrackNodeInput): boolean => {
      if (!highlightedRange) return false;
      const chIds = resolveChapterIds(node);
      if (chIds.length > 0) {
        return chIds.some((cid) => cid >= highlightedRange[0] && cid <= highlightedRange[1]);
      }
      return typeof node.anchor_chapter_id === "number" && node.anchor_chapter_id >= highlightedRange[0] && node.anchor_chapter_id <= highlightedRange[1];
    },
    [highlightedRange],
  );

  const sortedNodes = useMemo(() => {
    if (!nodes) return [];
    if (!derivedOrder || derivedOrder.length === 0) {
      return [...nodes].sort((a, b) => {
        const prog = (a.progress ?? 0) - (b.progress ?? 0);
        if (prog !== 0) return prog;
        const aStart = a.char_start ?? Number.MAX_SAFE_INTEGER;
        const bStart = b.char_start ?? Number.MAX_SAFE_INTEGER;
        if (aStart !== bStart) return aStart - bStart;
        return (a.char_end ?? Number.MAX_SAFE_INTEGER) - (b.char_end ?? Number.MAX_SAFE_INTEGER);
      });
    }
    const orderIndexMap = new Map(derivedOrder.map((id, i) => [id, i] as const));
    return [...nodes].sort((a, b) => {
      const aIdx = orderIndexMap.get(a.root_event_id ?? "") ?? orderIndexMap.get(a.tree_id ?? "") ?? null;
      const bIdx = orderIndexMap.get(b.root_event_id ?? "") ?? orderIndexMap.get(b.tree_id ?? "") ?? null;
      if (aIdx != null && bIdx != null) return aIdx - bIdx;
      if (aIdx != null) return -1;
      if (bIdx != null) return 1;
      const prog = (a.progress ?? 0) - (b.progress ?? 0);
      if (prog !== 0) return prog;
      const aStart = a.char_start ?? Number.MAX_SAFE_INTEGER;
      const bStart = b.char_start ?? Number.MAX_SAFE_INTEGER;
      if (aStart !== bStart) return aStart - bStart;
      const aEnd = a.char_end ?? Number.MAX_SAFE_INTEGER;
      const bEnd = b.char_end ?? Number.MAX_SAFE_INTEGER;
      if (aEnd !== bEnd) return aEnd - bEnd;
      return String(a.root_event_id ?? a.tree_id).localeCompare(String(b.root_event_id ?? b.tree_id));
    });
  }, [nodes, derivedOrder]);

  const canvasMinWidth = useMemo(
    () => calculateCanvasMinWidth(sortedNodes.length, totalChapters),
    [sortedNodes.length, totalChapters],
  );

  const layoutNodes = useMemo(
    () => createTimelineLayoutNodes(sortedNodes, derivedOrder, canvasMinWidth, { tensionCurve, totalChapters }),
    [canvasMinWidth, sortedNodes, derivedOrder, tensionCurve, totalChapters],
  );

  const tensionPath = useMemo(() => {
    if (!tensionCurve || tensionCurve.length === 0) {
      return null;
    }
    return buildTensionAreaPath(tensionCurve, totalChapters, canvasMinWidth);
  }, [canvasMinWidth, tensionCurve, totalChapters]);

  const phaseLayouts = useMemo(() => {
    if (!phases || phases.length === 0) return [];

    let accumulatedRatio = 0;
    return phases.map((phase, index) => {
      const left = accumulatedRatio * canvasMinWidth;
      accumulatedRatio += phase.ratio;
      const rawRight = index === phases.length - 1 ? canvasMinWidth : accumulatedRatio * canvasMinWidth;
      return {
        ...phase,
        left,
        width: Math.max(rawRight - left, 0),
      };
    });
  }, [canvasMinWidth, phases]);

  return (
    <div className={cn("relative flex h-full min-h-0 flex-col overflow-hidden rounded-[28px] border border-border/70 bg-background/80", className)}>
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(255,255,255,0.8),transparent_45%),linear-gradient(180deg,rgba(255,255,255,0.92),rgba(247,240,236,0.76))]" />

      <div className="relative flex min-h-0 flex-1 flex-col pb-2 pt-1">
        <div className="min-h-0 flex-1 overflow-x-auto overflow-y-hidden px-2 pb-1">
          <div className="h-full w-max min-w-full">
            <div
              className="relative h-full min-h-[430px] overflow-hidden rounded-[24px] border border-white/60 bg-[radial-gradient(circle_at_top_left,rgba(255,255,255,0.72),transparent_42%),linear-gradient(180deg,rgba(255,255,255,0.7),rgba(247,240,236,0.4))]"
              style={{ minWidth: `${canvasMinWidth}px` }}
            >
              {phaseLayouts.map((phase) => {
                const isActive = activePhase === phase.name;
                return (
                  <div
                    key={phase.name}
                    className={cn(
                      "absolute rounded-[24px] border border-white/70 bg-gradient-to-b",
                      PHASE_SURFACE_CLASS_MAP[phase.name] ?? "from-primary/12 to-primary/4",
                      isActive && "shadow-[0_0_0_2px_rgba(255,255,255,0.75)]",
                    )}
                    style={{
                      left: `${phase.left}px`,
                      width: `${phase.width}px`,
                      top: `${PHASE_BAND_TOP_PX}px`,
                      bottom: `${PHASE_BAND_BOTTOM_PX}px`,
                    }}
                  />
                );
              })}

              {tensionPath && (
                <svg
                  className="pointer-events-none absolute inset-0"
                  viewBox={`0 0 ${canvasMinWidth} ${TRACK_HEIGHT_PX}`}
                  preserveAspectRatio="none"
                >
                  <defs>
                    <linearGradient id="timeline-tension-fill" x1="0" x2="0" y1="0" y2="1">
                      <stop offset="0%" stopColor="rgba(191, 110, 52, 0.22)" />
                      <stop offset="100%" stopColor="rgba(191, 110, 52, 0.02)" />
                    </linearGradient>
                  </defs>
                  <path d={tensionPath.areaPath} fill="url(#timeline-tension-fill)" />
                  <path
                    d={tensionPath.linePath}
                    fill="none"
                    stroke="rgba(171, 98, 44, 0.7)"
                    strokeWidth="2.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              )}

              <div className="relative h-full" style={{ minHeight: `${TRACK_HEIGHT_PX}px`, minWidth: `${canvasMinWidth}px` }}>
                {/* 跨章区间半透明带宽条 */}
                {layoutNodes.map((layoutNode) => {
                  const { node, anchorY } = layoutNode;
                  const isCrossChapter = node.start_chapter_id !== node.end_chapter_id;
                  if (!isCrossChapter) return null;
                  const spanWidth = getEventSpanWidth(node, canvasMinWidth, totalChapters);
                  const usableMinProgress = Math.min(node.start_progress, node.end_progress);
                  const spanLeft = getTrackPositionPx(usableMinProgress, canvasMinWidth, TRACK_NODE_START_PADDING_PX, TRACK_NODE_END_PADDING_PX);
                  // 若 spanWidth 为 labelWidth（单章）则不渲染带宽
                  if (spanWidth <= 0) return null;
                  return (
                    <div
                      key={`span-${resolveNodeKey(node)}`}
                      data-testid="timeline-span"
                      className="pointer-events-none absolute rounded-full bg-primary/10 border border-primary/15"
                      style={{
                        left: `${spanLeft}px`,
                        width: `${spanWidth}px`,
                        top: `${anchorY - 6}px`,
                        height: "12px",
                      }}
                    />
                  );
                })}

                {layoutNodes.map((layoutNode, index) => {
                  const { node, lane, labelWidth, anchorX, anchorY } = layoutNode;
                  const labelTop = getLabelTopPx(anchorY, lane);
                  const labelLeft = anchorX - labelWidth / 2;
                  const labelAnchorY = lane < 0 ? labelTop + LABEL_HEIGHT_PX : labelTop;
                  const subtype = getEventPresentationSubtype(node);
                  const presentation = getTimelineNodePresentation(node.node_type as "event", subtype);
                  const nodeKey = resolveNodeKey(node);
                  const isSelected = selectedNodeId === nodeKey;
                  const isHighlighted = isNodeInHighlight(node);
                  const chapterLabel =
                    node.start_chapter_id !== node.end_chapter_id
                      ? `第 ${node.start_chapter_id}-${node.end_chapter_id} 章`
                      : `第 ${node.anchor_chapter_id} 章`;

                  return (
                    <div key={nodeKey}>
                      <svg
                        aria-hidden="true"
                        className="pointer-events-none absolute inset-0 overflow-visible"
                        viewBox={`0 0 ${canvasMinWidth} ${TRACK_HEIGHT_PX}`}
                      >
                        <line
                          data-testid="timeline-connector"
                          x1={anchorX}
                          y1={anchorY}
                          x2={anchorX}
                          y2={labelAnchorY}
                          className={cn(
                            "stroke-current text-border/80",
                            isSelected && "text-primary/70",
                            isHighlighted && !isSelected && "text-chart-4/70",
                          )}
                          strokeWidth="1"
                        />
                      </svg>

                      <motion.button
                        type="button"
                        className={cn(
                          "absolute z-[5] flex h-[68px] items-start gap-2 overflow-hidden rounded-xl border px-3 py-2 text-left shadow-sm backdrop-blur-sm transition-all",
                          "hover:-translate-y-0.5 hover:shadow-md",
                          isSelected
                            ? "border-primary/35 bg-primary/10 shadow-[0_12px_30px_rgba(161,90,43,0.16)]"
                            : "border-white/80 bg-background/88 hover:border-border/80",
                          isHighlighted && !isSelected && "border-chart-4/35 bg-chart-4/8",
                        )}
                        style={{
                          left: `${labelLeft}px`,
                          top: `${labelTop}px`,
                          width: `${labelWidth}px`,
                        }}
                        data-testid="timeline-card"
                        data-card-order={index + 1}
                        data-lane={lane}
                        onClick={() => onNodeClick?.(node)}
                      >
                        <div
                          className={cn(
                            "mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border",
                            presentation.dotClassName,
                          )}
                        >
                          <presentation.icon className={cn("h-3 w-3", presentation.iconClassName)} />
                        </div>
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-1.5">
                            <span className="text-[11px] font-semibold text-text">{presentation.label}</span>
                            <span className="text-[11px] text-text-muted">{chapterLabel}</span>
                          </div>
                          <p className="mt-0.5 line-clamp-1 text-xs leading-4 text-text">{node.summary}</p>
                        </div>
                      </motion.button>
                    </div>
                  );
                })}

                {layoutNodes.length === 0 ? (
                  <div className="flex h-full items-center justify-center text-sm text-text-muted">暂无时间轴节点</div>
                ) : null}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
