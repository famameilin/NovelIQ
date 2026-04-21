/**
 * TimelineTrack - 叙事时间轴主视图组件
 *
 * 创建时间: 2026-04-05
 * 创建者: GLM-5
 * 任务: Phase 2-B 叙事时间轴
 * 说明: 横向时间轴轨道，包含节点和连接线
 *
 * 修改时间: 2026-04-21
 * 任务: 重设计叙事时间轴主视觉
 * 修改内容:
 *   - 将单线点阵改为“阶段背景 + 节奏底图 + 上下分层节点”的叙事视图
 *   - 让密集节点通过多层车道避让，减少右侧拥挤和横向滚动依赖
 *   - 为每个节点补上短标签与引导线，真正占用下半区表达信息
 *
 * 修改时间: 2026-04-21
 * 任务: 优化时间轴密集节点的可读性
 * 修改内容:
 *   - 为主轨道增加横向滚动容器，让密集节点优先展开而不是硬挤
 *   - 放大画布宽度和首尾安全边距，减少节点与标签贴边感
 *   - 为滚动区域补充底部留白，让滚动条和时间轴内容更易区分
 *
 * 修改时间: 2026-04-21
 * 任务: 修复时间轴滚动后的背景与圆角表现
 * 修改内容:
 *   - 将阶段背景与张力底图并入可滚动画布，确保随时间轴宽度一起延展
 *   - 恢复滚动主图区的圆角裁切，避免出现生硬直角块面
 *   - 统一滚动画布的背景层，减少前景滚动与背景静止的割裂感
 *
 * 修改时间: 2026-04-21
 * 任务: 第一版节点贴合张力曲线
 * 修改内容:
 *   - 节点圆点按 progress 插值吸附到张力曲线，增强事件与节奏的对应关系
 *   - 保留标签分层避让，仅让锚点贴线，避免密集区瞬间失去可读性
 *   - 收紧图例与主图之间的外部间隙，同时在轨道内部补一点上下呼吸空间
 *
 * 修改时间: 2026-04-21
 * 任务: 第二版时间轴主轴视觉收敛
 * 修改内容:
 *   - 移除中部旧基线，让张力曲线直接承担时间轴主轴角色
 *   - 将张力曲线提升到画布中段，节点围绕曲线分布而不是落在下半区
 *   - 将内部留白转移为色块与上下标签卡之间的呼吸空间，减少无效空白
 */

import { motion } from "framer-motion";
import { useMemo, useCallback } from "react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/cn";
import type { TimelineNode as TimelineNodeType } from "@/api/types";
import { TimelineNode } from "./TimelineNode";
import { getTimelineNodePresentation } from "./timelineNodePresentation";

export interface TimelineTrackProps {
  nodes: TimelineNodeType[];
  phases?: { name: string; start: number; end: number; ratio: number }[];
  activePhase?: string;
  selectedNodeId?: number;
  onNodeClick?: (node: TimelineNodeType) => void;
  className?: string;
  tensionCurve?: number[];
  totalChunks?: number;
  showTension?: boolean;
}

interface TimelineLayoutNode {
  node: TimelineNodeType;
  lane: number;
  labelWidth: number;
}

const TRACK_NODE_START_PADDING_PX = 28;
const TRACK_NODE_END_PADDING_PX = 68;
const TRACK_CURVE_START_PADDING_PX = 28;
const TRACK_CURVE_END_PADDING_PX = 68;
const TRACK_LABEL_START_GAP_PX = 16;
const TRACK_LABEL_END_GAP_PX = 38;
const TRACK_HEIGHT_PX = 376;
const TRACK_BASELINE_Y = 172;
const TRACK_MIN_WIDTH_PX = 980;
const TRACK_NODE_SPACING_PX = 136;
const TRACK_CHUNK_SPACING_PX = 46;
const LANE_GAP_PX = 48;
const LABEL_HEIGHT_PX = 58;
const TOP_LABEL_MARGIN_PX = 12;
const BOTTOM_LABEL_MARGIN_PX = 44;
const PHASE_BAND_TOP_PX = 28;
const PHASE_BAND_BOTTOM_PX = 28;
const TOP_LABEL_CLEARANCE_PX = 18;
const BOTTOM_LABEL_CLEARANCE_PX = 20;
const CURVE_CENTER_Y = 176;
const CURVE_AMPLITUDE_PX = 52;
const NODE_RENDER_OFFSET_X_PX = -8;
const NODE_RENDER_OFFSET_Y_PX = -9;
const GUIDE_LINE_OFFSET_X_PX = 8;
const GUIDE_LINE_OFFSET_Y_PX = 2;
const LANE_ORDER = [-2, -1, 1, 2] as const;

const PHASE_SURFACE_CLASS_MAP: Record<string, string> = {
  引入期: "from-chart-1/12 to-chart-1/4",
  发展期: "from-chart-2/12 to-chart-2/4",
  高潮期: "from-chart-3/12 to-chart-3/4",
  收束期: "from-chart-4/12 to-chart-4/4",
};

export function TimelineTrack({
  nodes,
  phases,
  activePhase,
  selectedNodeId,
  onNodeClick,
  className,
  tensionCurve,
  totalChunks = 0,
  showTension = true,
}: TimelineTrackProps) {
  const highlightedRange = useMemo(() => {
    if (!activePhase || !phases) return null;
    const phase = phases.find((item) => item.name === activePhase);
    return phase ? [phase.start, phase.end] as [number, number] : null;
  }, [activePhase, phases]);

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
    return Math.max(
      TRACK_MIN_WIDTH_PX,
      sortedNodes.length * TRACK_NODE_SPACING_PX,
      Math.max(totalChunks, 0) * TRACK_CHUNK_SPACING_PX
    );
  }, [sortedNodes.length, totalChunks]);

  const layoutNodes = useMemo(() => {
    return createTimelineLayoutNodes(sortedNodes, canvasMinWidth);
  }, [canvasMinWidth, sortedNodes]);

  const tensionPath = useMemo(() => {
    if (!showTension || !tensionCurve || tensionCurve.length === 0) {
      return null;
    }
    return buildTensionAreaPath(tensionCurve, totalChunks, canvasMinWidth);
  }, [canvasMinWidth, showTension, tensionCurve, totalChunks]);

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
    <div className={cn("relative overflow-hidden rounded-[28px] border border-border/70 bg-background/80", className)}>
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(255,255,255,0.8),transparent_45%),linear-gradient(180deg,rgba(255,255,255,0.92),rgba(247,240,236,0.76))]" />

      <div className="relative pb-5 pt-4">
        <div className="flex flex-wrap items-center justify-between gap-3 px-5">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="outline" className="border-border/70 bg-background/85 text-text">
              {sortedNodes.length} 个关键节点
            </Badge>
            <Badge variant="outline" className="border-border/70 bg-background/85 text-text-muted">
              曲线表示叙事主轴
            </Badge>
            {showTension ? (
              <Badge variant="outline" className="border-border/70 bg-background/85 text-text-muted">
                底图表示节奏张力
              </Badge>
            ) : null}
          </div>
          <div className="text-xs text-text-muted">点击节点可在下方查看完整叙事细节</div>
        </div>

        <div className="mt-3 overflow-x-auto overflow-y-hidden px-2 pb-3">
          <div className="w-max min-w-full">
            <div
              className="relative overflow-hidden rounded-[24px] border border-white/60 bg-[radial-gradient(circle_at_top_left,rgba(255,255,255,0.72),transparent_42%),linear-gradient(180deg,rgba(255,255,255,0.7),rgba(247,240,236,0.4))]"
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
                      isActive && "shadow-[0_0_0_2px_rgba(255,255,255,0.75)]"
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

              <div className="relative" style={{ height: `${TRACK_HEIGHT_PX}px`, minWidth: `${canvasMinWidth}px` }}>
                {layoutNodes.map((layoutNode, index) => {
                  const { node, lane, labelWidth } = layoutNode;
                  const anchorX = getTrackPositionPx(
                    node.progress,
                    canvasMinWidth,
                    TRACK_NODE_START_PADDING_PX,
                    TRACK_NODE_END_PADDING_PX
                  );
                  const anchorY =
                    showTension && tensionCurve && tensionCurve.length > 0
                      ? getCurveNodeYPx(node.progress, tensionCurve, totalChunks)
                      : TRACK_BASELINE_Y + lane * LANE_GAP_PX;
                  const calibratedAnchorX = anchorX + NODE_RENDER_OFFSET_X_PX;
                  const calibratedAnchorY = anchorY + NODE_RENDER_OFFSET_Y_PX;
                  const guideLineX = calibratedAnchorX + GUIDE_LINE_OFFSET_X_PX;
                  const guideLineY = calibratedAnchorY + GUIDE_LINE_OFFSET_Y_PX;
                  const labelTop = getLabelTopPx(anchorY, lane);
                  const labelLeft = getClampedLabelLeftPx(anchorX, labelWidth, canvasMinWidth);
                  const labelAnchorY = lane < 0 ? labelTop + LABEL_HEIGHT_PX : labelTop;
                  const presentation = getTimelineNodePresentation(node.node_type);
                  const isSelected = selectedNodeId === node.chunk_id;
                  const isHighlighted = isNodeInHighlight(node);

                  return (
                    <div key={node.chunk_id}>
                      <motion.div
                        className={cn(
                          "absolute w-px bg-border/80",
                          isSelected && "bg-primary/70",
                          isHighlighted && !isSelected && "bg-chart-4/70"
                        )}
                        style={{
                          left: `${guideLineX}px`,
                          top: `${Math.min(guideLineY, labelAnchorY)}px`,
                          height: `${Math.max(Math.abs(labelAnchorY - guideLineY), 2)}px`,
                        }}
                        initial={{ scaleY: 0, opacity: 0.3 }}
                        animate={{ scaleY: 1, opacity: 1 }}
                        transition={{ duration: 0.25, delay: index * 0.03 }}
                      />

                      <motion.button
                        type="button"
                        className={cn(
                          "absolute z-[5] flex items-start gap-2 rounded-2xl border px-3 py-2 text-left shadow-sm backdrop-blur-sm transition-all",
                          "hover:-translate-y-0.5 hover:shadow-md",
                          isSelected
                            ? "border-primary/35 bg-primary/10 shadow-[0_12px_30px_rgba(161,90,43,0.16)]"
                            : "border-white/80 bg-background/88 hover:border-border/80",
                          isHighlighted && !isSelected && "border-chart-4/35 bg-chart-4/8"
                        )}
                        style={{
                          left: `${labelLeft}px`,
                          top: `${labelTop}px`,
                          width: `${labelWidth}px`,
                        }}
                        onClick={() => onNodeClick?.(node)}
                      >
                        <div
                          className={cn(
                            "mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border",
                            presentation.dotClassName
                          )}
                        >
                          <presentation.icon className={cn("h-3.5 w-3.5", presentation.iconClassName)} />
                        </div>
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-1.5">
                            <span className="text-[11px] font-semibold text-text">{presentation.label}</span>
                            <span className="text-[11px] text-text-muted">Chunk {node.chunk_id}</span>
                          </div>
                          <p className="mt-1 line-clamp-2 text-xs leading-5 text-text">
                            {node.event}
                          </p>
                        </div>
                      </motion.button>

                      <TimelineNode
                        node={node}
                        baselineY={calibratedAnchorY}
                        position={`${calibratedAnchorX}px`}
                        verticalOffset={0}
                        isSelected={isSelected}
                        isHighlighted={isHighlighted}
                        onClick={() => onNodeClick?.(node)}
                      />
                    </div>
                  );
                })}

                {layoutNodes.length === 0 ? (
                  <div className="flex h-full items-center justify-center text-sm text-text-muted">
                    暂无时间轴节点
                  </div>
                ) : null}
              </div>
            </div>

            <div className="mt-4 flex items-center justify-between px-1 text-xs text-text-muted">
              <span>开篇</span>
              <span>叙事张力逐步累积</span>
              <span>结尾</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

/**
 * 2026-04-21，任务：重设计叙事时间轴主视觉
 * 新建原因：给密集节点分配上下车道，避免标签在同一条线上相互覆盖。
 */
function createTimelineLayoutNodes(nodes: TimelineNodeType[], canvasWidth: number): TimelineLayoutNode[] {
  const laneLastEndMap = new Map<number, number>(LANE_ORDER.map((lane) => [lane, -1]));

  return nodes.map((node, index) => {
    const labelWidth = estimateLabelWidth(node.event);
    const labelWidthRatio = labelWidth / canvasWidth;
    const nodeLeft = getNormalizedProgress(node.progress);
    const labelStart = nodeLeft - labelWidthRatio / 2;

    const preferredLaneOrder = index % 2 === 0 ? [...LANE_ORDER] : [...LANE_ORDER].reverse();
    const lane =
      preferredLaneOrder.find((candidateLane) => {
        const lastEnd = laneLastEndMap.get(candidateLane) ?? -1;
        return labelStart > lastEnd + 0.018;
      }) ??
      preferredLaneOrder.reduce((bestLane, candidateLane) => {
        const bestEnd = laneLastEndMap.get(bestLane) ?? Number.POSITIVE_INFINITY;
        const candidateEnd = laneLastEndMap.get(candidateLane) ?? Number.POSITIVE_INFINITY;
        return candidateEnd < bestEnd ? candidateLane : bestLane;
      }, preferredLaneOrder[0]);

    const labelEnd = nodeLeft + labelWidthRatio / 2;
    laneLastEndMap.set(lane, labelEnd);

    return {
      node,
      lane,
      labelWidth,
    };
  });
}

/**
 * 2026-04-21，任务：重设计叙事时间轴主视觉
 * 新建原因：时间轴标签需要稳定宽度估算，以便在纯前端布局阶段做近似避让。
 */
function estimateLabelWidth(eventText: string): number {
  const estimated = eventText.trim().length * 11 + 56;
  return Math.max(120, Math.min(188, estimated));
}

/**
 * 2026-04-21，任务：重设计叙事时间轴主视觉
 * 新建原因：张力曲线改为时间轴底图后，需要一个轻量 SVG path 而不是单独的图表卡片。
 */
function buildTensionAreaPath(tensionCurve: number[], totalChunks: number, canvasWidth: number) {
  const normalizedPoints = tensionCurve.map((value, index) => {
    const xProgress = totalChunks > 1 ? index / Math.max(totalChunks - 1, 1) : index / Math.max(tensionCurve.length - 1, 1);
    const clampedValue = Number.isFinite(value) ? value : 0;
    return {
      x: getTrackPositionPx(
        xProgress,
        canvasWidth,
        TRACK_CURVE_START_PADDING_PX,
        TRACK_CURVE_END_PADDING_PX
      ),
      y: mapTensionValueToTrackY(clampedValue, tensionCurve),
    };
  });

  if (normalizedPoints.length === 0) {
    return null;
  }

  const linePath = normalizedPoints
    .map((point, index) => `${index === 0 ? "M" : "L"} ${point.x.toFixed(2)} ${point.y.toFixed(2)}`)
    .join(" ");

  const areaFloor = TRACK_HEIGHT_PX - 34;
  const areaPath = `${linePath} L ${normalizedPoints[normalizedPoints.length - 1]?.x.toFixed(2)} ${areaFloor} L ${normalizedPoints[0]?.x.toFixed(2)} ${areaFloor} Z`;

  return { linePath, areaPath };
}

/**
 * 2026-04-21，任务：第一版节点贴合张力曲线
 * 新建原因：节点需要按 progress 在张力曲线上插值定位，不能直接复用全局 percentile 当作图上坐标。
 */
function getCurveNodeYPx(progress: number, tensionCurve: number[], totalChunks: number): number {
  if (tensionCurve.length === 0) {
    return CURVE_CENTER_Y;
  }

  const interpolatedValue = interpolateSeriesValueAtProgress(progress, tensionCurve, totalChunks);
  return mapTensionValueToTrackY(interpolatedValue, tensionCurve);
}

/**
 * 2026-04-21，任务：拉开下方标签与曲线的距离
 * 新建原因：节点锚点已经贴曲线后，标签垂直位置必须相对曲线计算，不能继续依赖固定基线。
 */
function getLabelTopPx(anchorY: number, lane: number): number {
  const laneOffset = lane * LANE_GAP_PX;
  const rawLabelTop =
    lane < 0
      ? anchorY + laneOffset - (LABEL_HEIGHT_PX + TOP_LABEL_MARGIN_PX)
      : anchorY + laneOffset + BOTTOM_LABEL_MARGIN_PX;

  const minLabelTop = PHASE_BAND_TOP_PX + TOP_LABEL_CLEARANCE_PX;
  const maxLabelTop =
    TRACK_HEIGHT_PX - PHASE_BAND_BOTTOM_PX - LABEL_HEIGHT_PX - BOTTOM_LABEL_CLEARANCE_PX;
  return Math.max(minLabelTop, Math.min(maxLabelTop, rawLabelTop));
}

/**
 * 2026-04-21，任务：重设计叙事时间轴主视觉
 * 新建原因：不同张力来源数值区间不同，底图需要先归一化后再映射到视图高度。
 */
function normalizeSeriesValue(value: number, series: number[]): number {
  const min = Math.min(...series);
  const max = Math.max(...series);
  if (max - min < 1e-6) {
    return 0.5;
  }
  return (value - min) / (max - min);
}

/**
 * 2026-04-21，任务：第二版时间轴主轴视觉收敛
 * 新建原因：张力曲线需要稳定落在画布中段，既承担主轴，又给上下标签保留呼吸空间。
 */
function mapTensionValueToTrackY(value: number, series: number[]): number {
  const normalized = normalizeSeriesValue(value, series);
  return CURVE_CENTER_Y + (0.5 - normalized) * CURVE_AMPLITUDE_PX * 2;
}

/**
 * 2026-04-21，任务：第一版节点贴合张力曲线
 * 新建原因：节点 progress 往往落在相邻张力采样点之间，需要线性插值才能贴到曲线本身。
 */
function interpolateSeriesValueAtProgress(progress: number, series: number[], totalChunks: number): number {
  if (series.length === 0) {
    return 0;
  }
  if (series.length === 1) {
    return series[0] ?? 0;
  }

  const normalized = getNormalizedProgress(progress);
  const maxIndex = totalChunks > 1 ? totalChunks - 1 : series.length - 1;
  const sampleIndex = normalized * Math.max(maxIndex, 1);
  const leftIndex = Math.max(0, Math.min(Math.floor(sampleIndex), series.length - 1));
  const rightIndex = Math.max(0, Math.min(Math.ceil(sampleIndex), series.length - 1));

  if (leftIndex === rightIndex) {
    return series[leftIndex] ?? 0;
  }

  const leftValue = series[leftIndex] ?? 0;
  const rightValue = series[rightIndex] ?? leftValue;
  const ratio = sampleIndex - leftIndex;
  return leftValue + (rightValue - leftValue) * ratio;
}

/**
 * 2026-04-21，任务：重设计叙事时间轴主视觉
 * 新建原因：节点与曲线都需要按可配置的首尾安全边距映射到画布坐标，便于单独加大末尾留白。
 */
function getTrackPositionPx(
  progress: number,
  canvasWidth: number,
  startPaddingPx: number,
  endPaddingPx: number
): number {
  const normalized = getNormalizedProgress(progress);
  return startPaddingPx + normalized * Math.max(canvasWidth - startPaddingPx - endPaddingPx, 0);
}

/**
 * 2026-04-21，任务：修复首尾标签裁切
 * 新建原因：首尾 chunk 的标签不能简单以节点为中心，需要在画布边缘内做钳制。
 */
function getClampedLabelLeftPx(anchorX: number, labelWidth: number, canvasWidth: number): number {
  const minLeft = TRACK_LABEL_START_GAP_PX;
  const maxLeft = Math.max(canvasWidth - labelWidth - TRACK_LABEL_END_GAP_PX, minLeft);
  return Math.min(Math.max(anchorX - labelWidth / 2, minLeft), maxLeft);
}

function getNormalizedProgress(progress: number): number {
  return Math.min(Math.max(progress, 0), 1);
}
