import type { TimelineCompositeNode, TimelineNode as TimelineNodeType } from "@/api/types";

import { getCurveNodeYPx, getNormalizedProgress, getTrackPositionPx, TRACK_HEIGHT_PX } from "./timelineTrackPaths";

type TimelineLayoutInputNode = TimelineNodeType | TimelineCompositeNode;
type TimelineSide = "top" | "bottom";

interface TimelineLayoutCandidate {
  node: TimelineLayoutInputNode;
  index: number;
  labelWidth: number;
  lane: number;
  anchorX: number;
  anchorY: number;
}

export interface TimelineLayoutNode {
  node: TimelineLayoutInputNode;
  lane: number;
  labelWidth: number;
  anchorX: number;
  anchorY: number;
}

export const TRACK_NODE_START_PADDING_PX = 28;
export const TRACK_NODE_END_PADDING_PX = 68;
export const TRACK_LABEL_START_GAP_PX = 16;
export const TRACK_LABEL_END_GAP_PX = 38;
export const TRACK_BASELINE_Y = 172;
export const TRACK_MIN_WIDTH_PX = 980;
export const LABEL_WIDTH_MIN_PX = 164;
export const LABEL_WIDTH_MAX_PX = 196;
export const LABEL_HEIGHT_PX = 68;
export const LABEL_VERTICAL_GAP_PX = 12;
export const LABEL_HORIZONTAL_GAP_PX = 16;
export const TRACK_NODE_SPACING_PX = (LABEL_WIDTH_MAX_PX + LABEL_HORIZONTAL_GAP_PX) / 2;
export const TRACK_CHUNK_SPACING_PX = 8;
export const TOP_LABEL_MARGIN_PX = 12;
export const BOTTOM_LABEL_MARGIN_PX = 44;
export const PHASE_BAND_TOP_PX = 16;
export const PHASE_BAND_BOTTOM_PX = 0;
export const TOP_LABEL_CLEARANCE_PX = 12;
export const BOTTOM_LABEL_CLEARANCE_PX = 10;
export const LANE_ORDER = [-2, -1, 1, 2] as const;

/**
 * 2026-08-17，作用：按事件摘要估算时间轴卡片宽度
 * 说明：在统一的最小和最大宽度内保留标题与摘要的可读性
 */
export function estimateLabelWidth(summaryText: string): number {
  const estimated = summaryText.trim().length * 11 + 56;
  return Math.max(LABEL_WIDTH_MIN_PX, Math.min(LABEL_WIDTH_MAX_PX, estimated));
}

/**
 * 2026-08-17，作用：计算给定方向可容纳的事件卡层数
 * 说明：第一层贴近时间轴，第二层远离时间轴
 */
function getLaneCapacity(room: number, lineGap: number): number {
  return Math.max(
    0,
    Math.floor((room - lineGap + LABEL_VERTICAL_GAP_PX) / (LABEL_HEIGHT_PX + LABEL_VERTICAL_GAP_PX)),
  );
}

/**
 * 2026-08-17，作用：根据时间轴曲线高度识别上下可用车道
 * 说明：曲线靠上时下方提供两层，曲线靠下时上方提供两层
 */
function getAvailableLanes(anchorY: number): Record<TimelineSide, number[]> {
  const topRoom = Math.max(0, anchorY - (PHASE_BAND_TOP_PX + TOP_LABEL_CLEARANCE_PX));
  const bottomRoom = Math.max(
    0,
    TRACK_HEIGHT_PX - PHASE_BAND_BOTTOM_PX - BOTTOM_LABEL_CLEARANCE_PX - anchorY,
  );
  const top = Array.from(
    { length: Math.min(getLaneCapacity(topRoom, TOP_LABEL_MARGIN_PX), 2) },
    (_, laneIndex) => -(laneIndex + 1),
  );
  const bottom = Array.from(
    { length: Math.min(getLaneCapacity(bottomRoom, BOTTOM_LABEL_MARGIN_PX), 2) },
    (_, laneIndex) => laneIndex + 1,
  );

  return { top, bottom };
}

/**
 * 2026-08-17，作用：按奇偶序号给事件卡选择交错车道
 * 说明：奇数卡固定第二层，偶数卡固定第一层，曲线偏上或偏下时让空间较多的一侧先排出二、一、二
 */
function getPreferredLaneOrder(anchorY: number, cardIndex: number): number[] {
  const availableLanes = getAvailableLanes(anchorY);
  const requestedLayer = cardIndex % 2 === 0 ? 2 : 1;
  const pairSide: TimelineSide = Math.floor(cardIndex / 2) % 2 === 0 ? "top" : "bottom";
  const topSupportsSecondLayer = availableLanes.top.some((lane) => Math.abs(lane) === 2);
  const bottomSupportsSecondLayer = availableLanes.bottom.some((lane) => Math.abs(lane) === 2);
  const roomierSide =
    topSupportsSecondLayer === bottomSupportsSecondLayer ? null : topSupportsSecondLayer ? "top" : "bottom";
  const constrainedSide: TimelineSide | null =
    roomierSide === "top" ? "bottom" : roomierSide === "bottom" ? "top" : null;
  const useConstrainedSide =
    requestedLayer === 1 && constrainedSide != null && Math.floor(cardIndex / 2) % 2 === 1;
  const preferredSide = useConstrainedSide ? constrainedSide : roomierSide ?? pairSide;
  const oppositeSide: TimelineSide = preferredSide === "top" ? "bottom" : "top";
  const preferredSides = [preferredSide, oppositeSide];
  const requestedLanes = preferredSides
    .map((side) => availableLanes[side].find((candidateLane) => Math.abs(candidateLane) === requestedLayer))
    .filter((lane): lane is number => lane != null);

  if (requestedLanes.length > 0) {
    return requestedLanes;
  }

  // 异常曲线输入时仍保留请求层级，避免偶数卡错误降到第二层或奇数卡错误升到第一层
  return [pairSide === "top" ? -requestedLayer : requestedLayer];
}

/**
 * 2026-08-17，作用：计算时间轴位置对应的曲线 Y 坐标
 * 说明：无张力曲线时回退到固定中线
 */
function getLayoutAnchorY(
  progress: number,
  options?: { tensionCurve?: number[]; totalChapters?: number },
): number {
  if (options?.tensionCurve && options.tensionCurve.length > 0) {
    return getCurveNodeYPx(progress, options.tensionCurve, options.totalChapters ?? 0);
  }

  return TRACK_BASELINE_Y;
}

/**
 * 2026-08-17，作用：将渲染横坐标转换为时间轴进度
 * 说明：连接线落点和张力曲线使用同一横坐标
 */
function getProgressForAnchorX(anchorX: number, canvasWidth: number): number {
  const usableWidth = Math.max(canvasWidth - TRACK_NODE_START_PADDING_PX - TRACK_NODE_END_PADDING_PX, 1);
  return getNormalizedProgress((anchorX - TRACK_NODE_START_PADDING_PX) / usableWidth);
}

/**
 * 2026-08-17，作用：按时间顺序铺开事件卡横坐标
 * 说明：所有事件共用一条从左到右的序列，防止上、下侧单独排版打乱奇偶顺序
 */
function packTimelineAnchors(candidates: TimelineLayoutCandidate[], canvasWidth: number): void {
  let previousAnchorX: number | null = null;

  candidates.forEach((candidate) => {
    const minAnchorX = TRACK_LABEL_START_GAP_PX + candidate.labelWidth / 2;
    candidate.anchorX = Math.max(candidate.anchorX, minAnchorX, (previousAnchorX ?? 0) + TRACK_NODE_SPACING_PX);
    previousAnchorX = candidate.anchorX;
  });

  let nextAnchorX: number | null = null;
  for (let candidateIndex = candidates.length - 1; candidateIndex >= 0; candidateIndex -= 1) {
    const candidate = candidates[candidateIndex];
    if (!candidate) {
      continue;
    }
    const maxAnchorX = canvasWidth - TRACK_LABEL_END_GAP_PX - candidate.labelWidth / 2;
    candidate.anchorX = Math.min(candidate.anchorX, maxAnchorX, (nextAnchorX ?? canvasWidth) - TRACK_NODE_SPACING_PX);
    nextAnchorX = candidate.anchorX;
  }
}

/**
 * 2026-08-17，作用：根据时间轴曲线位置布局事件卡
 * 说明：奇偶卡交错进入第一和第二层，并让连接线与卡片中心保持同一竖直列
 */
export function createTimelineLayoutNodes(
  nodes: TimelineLayoutInputNode[],
  canvasWidth: number,
  options?: { tensionCurve?: number[]; totalChapters?: number },
): TimelineLayoutNode[] {
  const candidates = nodes.map((node, index) => {
    const anchorX = calculateNodeAnchorX(node.progress, canvasWidth);
    return {
      node,
      index,
      labelWidth: estimateLabelWidth(node.summary),
      lane: 0,
      anchorX,
      anchorY: getLayoutAnchorY(node.progress, options),
    };
  });

  packTimelineAnchors(candidates, canvasWidth);
  candidates.forEach((candidate) => {
    const renderProgress = getProgressForAnchorX(candidate.anchorX, canvasWidth);
    candidate.anchorY = getLayoutAnchorY(renderProgress, options);
    candidate.lane = getPreferredLaneOrder(candidate.anchorY, candidate.index)[0] ?? 1;
  });

  return candidates.map((candidate) => ({
    node: candidate.node,
    lane: candidate.lane,
    labelWidth: candidate.labelWidth,
    anchorX: candidate.anchorX,
    anchorY: getLayoutAnchorY(getProgressForAnchorX(candidate.anchorX, canvasWidth), options),
  }));
}

/**
 * 2026-08-17，作用：计算容纳事件卡的时间轴最小宽度
 * 说明：每个事件预留最大卡片宽度和横向间距，保证横向滚动后的可读性
 */
export function calculateCanvasMinWidth(nodeCount: number, totalChapters: number): number {
  const densityWidth =
    Math.max(nodeCount - 1, 0) * TRACK_NODE_SPACING_PX +
    TRACK_LABEL_START_GAP_PX +
    LABEL_WIDTH_MAX_PX +
    TRACK_LABEL_END_GAP_PX;
  const chapterWidth = Math.min(Math.max(totalChapters, 0), 180) * TRACK_CHUNK_SPACING_PX;
  return Math.max(TRACK_MIN_WIDTH_PX, densityWidth, chapterWidth);
}

/**
 * 2026-08-17，作用：计算事件卡在指定车道的顶部坐标
 * 说明：顶部和底部卡片均保留与时间轴及阶段背景的安全间距
 */
export function getLabelTopPx(anchorY: number, lane: number): number {
  const laneIndex = lane < 0 ? Math.max(0, Math.abs(lane) - 1) : Math.max(0, lane - 1);
  const laneStart = lane < 0
    ? anchorY - TOP_LABEL_MARGIN_PX - LABEL_HEIGHT_PX - laneIndex * (LABEL_HEIGHT_PX + LABEL_VERTICAL_GAP_PX)
    : anchorY + BOTTOM_LABEL_MARGIN_PX + laneIndex * (LABEL_HEIGHT_PX + LABEL_VERTICAL_GAP_PX);
  const minLabelTop = PHASE_BAND_TOP_PX + TOP_LABEL_CLEARANCE_PX;
  const maxLabelTop = TRACK_HEIGHT_PX - PHASE_BAND_BOTTOM_PX - LABEL_HEIGHT_PX - BOTTOM_LABEL_CLEARANCE_PX;
  return Math.max(minLabelTop, Math.min(maxLabelTop, laneStart));
}

/**
 * 2026-08-17，作用：将卡片左边界限制在可滚动画布内
 * 说明：保留首尾安全边距，避免卡片被裁切
 */
export function getClampedLabelLeftPx(anchorX: number, labelWidth: number, canvasWidth: number): number {
  const minLeft = TRACK_LABEL_START_GAP_PX;
  const maxLeft = Math.max(canvasWidth - labelWidth - TRACK_LABEL_END_GAP_PX, minLeft);
  return Math.min(Math.max(anchorX - labelWidth / 2, minLeft), maxLeft);
}

/**
 * 2026-08-17，作用：计算节点的默认时间轴横坐标
 * 说明：用于布局前保留事件原始时间进度
 */
export function calculateNodeAnchorX(progress: number, canvasWidth: number): number {
  return getTrackPositionPx(progress, canvasWidth, TRACK_NODE_START_PADDING_PX, TRACK_NODE_END_PADDING_PX);
}

/**
 * 2026-08-17，作用：计算节点原始时间进度对应的曲线纵坐标
 * 说明：对外保留该计算入口，布局内部使用重排后的横坐标计算连接线落点
 */
export function calculateNodeAnchorY(
  progress: number,
  _lane: number,
  options: {
    tensionCurve?: number[];
    totalChapters: number;
  },
): number {
  const { tensionCurve, totalChapters } = options;
  if (tensionCurve && tensionCurve.length > 0) {
    return getCurveNodeYPx(progress, tensionCurve, totalChapters);
  }

  return TRACK_BASELINE_Y;
}
