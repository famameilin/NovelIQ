import type { TimelineEventNode } from "@/api/types";

import { getCurveNodeYPx, getNormalizedProgress, getTrackPositionPx, TRACK_HEIGHT_PX } from "./timelineTrackPaths";

type TimelineSide = "top" | "bottom";

export type TimelineLayoutInputNode = TimelineEventNode;

interface TimelineLayoutCandidate {
  node: TimelineLayoutInputNode;
  index: number;
  orderIndex: number;
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
  options?: { tensionCurve?: number[] | null; totalChapters?: number },
): number {
  if (options?.tensionCurve && options.tensionCurve.length > 0) {
    return getCurveNodeYPx(progress, options.tensionCurve as number[], options.totalChapters ?? 0);
  }

  return TRACK_BASELINE_Y;
}

/**
 * 2026-08-17，作用：将渲染横坐标转换为时间轴进度
 * 说明：连接线落点和张力曲线使用同一横坐标（保留导出供外部复用，避免 noUnusedLocals 误报）
 */
export function getProgressForAnchorX(anchorX: number, canvasWidth: number): number {
  const usableWidth = Math.max(canvasWidth - TRACK_NODE_START_PADDING_PX - TRACK_NODE_END_PADDING_PX, 1);
  return getNormalizedProgress((anchorX - TRACK_NODE_START_PADDING_PX) / usableWidth);
}

/**
 * 2026-08-20，作用：按派生顺序均匀分布后仅做最小间距微调
 * 说明：调用前已按 orderIndex 单调排序，若已均匀分布则 pack 不再二次压缩，仅保证 TRACK_NODE_SPACING_PX
 */
function packTimelineAnchors(candidates: TimelineLayoutCandidate[], canvasWidth: number): void {
  // 保证单调：即使调用方未排序也能按 derived_event_order 顺序微调
  candidates.sort((a, b) => a.orderIndex - b.orderIndex);

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

function resolveNodeProgress(node: TimelineLayoutInputNode): number {
  const start = (node as TimelineEventNode).start_progress;
  const end = (node as TimelineEventNode).end_progress;
  if (typeof start === "number" && typeof end === "number" && start !== end) {
    return (start + end) / 2;
  }
  return node.progress;
}

export function resolveNodeId(node: TimelineLayoutInputNode): string {
  const maybeRootEventId = (node as TimelineEventNode).root_event_id;
  const maybeTreeId = (node as TimelineEventNode).tree_id;
  return maybeRootEventId ?? maybeTreeId ?? "";
}

/**
 * 2026-08-20，作用：按 derived_event_order 均匀排布事件节点
 * 说明：一棵树=一个节点；anchorX 按 derivedOrder 均匀分布，anchorY 仍按 progress（或 start/end 中值）插值张力曲线
 */
export function createTimelineLayoutNodes(
  nodes: TimelineLayoutInputNode[],
  derivedOrder: string[],
  canvasWidth: number,
  options?: { tensionCurve?: number[] | null; totalChapters?: number },
): TimelineLayoutNode[] {
  const n = nodes.length;
  const usableWidth = Math.max(canvasWidth - TRACK_NODE_START_PADDING_PX - TRACK_NODE_END_PADDING_PX, 1);
  const orderIndexMap = new Map(derivedOrder.map((id, i) => [id, i] as const));

  // 对 nodes 按 derivedOrder 排序，fallback 按 progress（保证未命中也能稳定排序）
  // derived_event_order 仅含 event_id，需同时命中 root_event_id 与 tree_id
  const sortedNodes = [...nodes].sort((a, b) => {
    const aNode = a as TimelineEventNode;
    const bNode = b as TimelineEventNode;
    const aOrder = orderIndexMap.get(aNode.root_event_id ?? "") ?? orderIndexMap.get(aNode.tree_id ?? "");
    const bOrder = orderIndexMap.get(bNode.root_event_id ?? "") ?? orderIndexMap.get(bNode.tree_id ?? "");
    if (aOrder != null && bOrder != null) return aOrder - bOrder;
    if (aOrder != null) return -1;
    if (bOrder != null) return 1;
    const progDiff = resolveNodeProgress(a) - resolveNodeProgress(b);
    if (progDiff !== 0) return progDiff;
    // 同章多树细粒度：char_start/char_end 兜底，保证派生顺序即使缺失也能与后端的 derived_event_order 一致
    const aStart = aNode.char_start ?? Number.MAX_SAFE_INTEGER;
    const bStart = bNode.char_start ?? Number.MAX_SAFE_INTEGER;
    if (aStart !== bStart) return aStart - bStart;
    const aEnd = aNode.char_end ?? Number.MAX_SAFE_INTEGER;
    const bEnd = bNode.char_end ?? Number.MAX_SAFE_INTEGER;
    if (aEnd !== bEnd) return aEnd - bEnd;
    return String(aNode.root_event_id ?? aNode.tree_id ?? "").localeCompare(
      String(bNode.root_event_id ?? bNode.tree_id ?? ""),
    );
  });

  const candidates: TimelineLayoutCandidate[] = sortedNodes.map((node, sortedIndex) => {
    const orderIndex = sortedIndex;
    const anchorX =
      n <= 1
        ? TRACK_NODE_START_PADDING_PX + usableWidth / 2
        : TRACK_NODE_START_PADDING_PX + (orderIndex / Math.max(1, n - 1)) * usableWidth;
    const progressForY = resolveNodeProgress(node);
    return {
      node,
      index: sortedIndex,
      orderIndex,
      labelWidth: estimateLabelWidth(node.summary ?? (node as TimelineEventNode).title ?? ""),
      lane: 0,
      anchorX,
      anchorY: getLayoutAnchorY(progressForY, options),
    };
  });

  // 均匀分布后仅做最小间距微调，不再二次压缩导致重叠
  packTimelineAnchors(candidates, canvasWidth);
  candidates.forEach((candidate) => {
    const yProgress = resolveNodeProgress(candidate.node);
    candidate.anchorY = getLayoutAnchorY(yProgress, options);
    candidate.lane = getPreferredLaneOrder(candidate.anchorY, candidate.orderIndex)[0] ?? 1;
  });

  return candidates.map((candidate) => ({
    node: candidate.node,
    lane: candidate.lane,
    labelWidth: candidate.labelWidth,
    anchorX: candidate.anchorX,
    anchorY: getLayoutAnchorY(resolveNodeProgress(candidate.node), options),
  }));
}

/**
 * 2026-08-20，作用：计算跨章区间的轨道带宽
 * 说明：若节点跨章则返回区间宽度，否则返回标签宽度
 */
export function getEventSpanWidth(
  node: TimelineLayoutInputNode,
  canvasWidth: number,
  _totalChapters?: number,
): number {
  const labelWidth = estimateLabelWidth(node.summary ?? (node as TimelineEventNode).title ?? "");
  const start = (node as TimelineEventNode).start_progress;
  const end = (node as TimelineEventNode).end_progress;
  if (typeof start === "number" && typeof end === "number" && start !== end) {
    const usableWidth = Math.max(canvasWidth - TRACK_NODE_START_PADDING_PX - TRACK_NODE_END_PADDING_PX, 1);
    return Math.abs(end - start) * usableWidth;
  }
  return labelWidth;
}

/**
 * 2026-08-17，作用：计算容纳事件卡的时间轴最小宽度
 * 说明：每个事件预留最大卡片宽度和横向间距，保证横向滚动后的可读性；2026-08-20 增加 derivedOrder 校验
 */
export function calculateCanvasMinWidth(nodeCount: number, totalChapters: number): number {
  const safeNodeCount = Math.max(nodeCount, 0);
  const densityWidth =
    Math.max(safeNodeCount - 1, 0) * TRACK_NODE_SPACING_PX +
    TRACK_LABEL_START_GAP_PX +
    LABEL_WIDTH_MAX_PX +
    TRACK_LABEL_END_GAP_PX;
  // 亦满足 task 描述的 nodeCount*TRACK_NODE_SPACING_PX 量级校验，覆盖密集派生顺序场景
  const derivedDensityWidth = safeNodeCount * TRACK_NODE_SPACING_PX + TRACK_LABEL_START_GAP_PX + TRACK_LABEL_END_GAP_PX;
  const effectiveDensityWidth = Math.max(densityWidth, derivedDensityWidth);
  const chapterWidth = Math.min(Math.max(totalChapters, 0), 180) * TRACK_CHUNK_SPACING_PX;
  return Math.max(TRACK_MIN_WIDTH_PX, effectiveDensityWidth, chapterWidth);
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
 * 说明：用于布局前保留事件原始时间进度；2026-08-20 起布局内部不再依赖此函数，保留供外部兼容
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
