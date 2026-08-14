import type { TimelineCompositeNode, TimelineNode as TimelineNodeType } from "@/api/types";

import { getCurveNodeYPx, getNormalizedProgress, getTrackPositionPx, TRACK_HEIGHT_PX } from "./timelineTrackPaths";

type TimelineLayoutInputNode = TimelineNodeType | TimelineCompositeNode;

export interface TimelineLayoutNode {
  node: TimelineLayoutInputNode;
  lane: number;
  labelWidth: number;
}

export const TRACK_NODE_START_PADDING_PX = 28;
export const TRACK_NODE_END_PADDING_PX = 68;
export const TRACK_LABEL_START_GAP_PX = 16;
export const TRACK_LABEL_END_GAP_PX = 38;
export const TRACK_BASELINE_Y = 172;
export const TRACK_MIN_WIDTH_PX = 980;
export const TRACK_NODE_SPACING_PX = 136;
export const TRACK_CHUNK_SPACING_PX = 46;
export const LANE_GAP_PX = 48;
export const LABEL_HEIGHT_PX = 72;
export const TOP_LABEL_MARGIN_PX = 12;
export const BOTTOM_LABEL_MARGIN_PX = 44;
export const PHASE_BAND_TOP_PX = 16;
export const PHASE_BAND_BOTTOM_PX = 0;
export const TOP_LABEL_CLEARANCE_PX = 12;
export const BOTTOM_LABEL_CLEARANCE_PX = 10;
export const NODE_RENDER_OFFSET_X_PX = -8;
export const NODE_RENDER_OFFSET_Y_PX = -9;
export const GUIDE_LINE_OFFSET_X_PX = 8;
export const GUIDE_LINE_OFFSET_Y_PX = 2;
export const LANE_ORDER = [-2, -1, 1, 2] as const;

export function estimateLabelWidth(summaryText: string): number {
  const estimated = summaryText.trim().length * 11 + 56;
  return Math.max(120, Math.min(188, estimated));
}

export function createTimelineLayoutNodes(nodes: TimelineLayoutInputNode[], canvasWidth: number): TimelineLayoutNode[] {
  const laneLastEndMap = new Map<number, number>(LANE_ORDER.map((lane) => [lane, -1]));

  return nodes.map((node, index) => {
    const labelWidth = estimateLabelWidth(node.summary);
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

export function calculateCanvasMinWidth(nodeCount: number, totalChunks: number): number {
  return Math.max(TRACK_MIN_WIDTH_PX, nodeCount * TRACK_NODE_SPACING_PX, Math.max(totalChunks, 0) * TRACK_CHUNK_SPACING_PX);
}

export function getLabelTopPx(anchorY: number, lane: number): number {
  const laneOffset = lane * LANE_GAP_PX;
  const rawLabelTop =
    lane < 0 ? anchorY + laneOffset - (LABEL_HEIGHT_PX + TOP_LABEL_MARGIN_PX) : anchorY + laneOffset + BOTTOM_LABEL_MARGIN_PX;

  const minLabelTop = PHASE_BAND_TOP_PX + TOP_LABEL_CLEARANCE_PX;
  const maxLabelTop = TRACK_HEIGHT_PX - PHASE_BAND_BOTTOM_PX - LABEL_HEIGHT_PX - BOTTOM_LABEL_CLEARANCE_PX;
  return Math.max(minLabelTop, Math.min(maxLabelTop, rawLabelTop));
}

export function getClampedLabelLeftPx(anchorX: number, labelWidth: number, canvasWidth: number): number {
  const minLeft = TRACK_LABEL_START_GAP_PX;
  const maxLeft = Math.max(canvasWidth - labelWidth - TRACK_LABEL_END_GAP_PX, minLeft);
  return Math.min(Math.max(anchorX - labelWidth / 2, minLeft), maxLeft);
}

export function calculateNodeAnchorX(progress: number, canvasWidth: number): number {
  return getTrackPositionPx(progress, canvasWidth, TRACK_NODE_START_PADDING_PX, TRACK_NODE_END_PADDING_PX);
}

export function calculateNodeAnchorY(
  progress: number,
  lane: number,
  options: {
    tensionCurve?: number[];
    totalChunks: number;
  }
): number {
  const { tensionCurve, totalChunks } = options;
  if (tensionCurve && tensionCurve.length > 0) {
    return getCurveNodeYPx(progress, tensionCurve, totalChunks);
  }
  return TRACK_BASELINE_Y + lane * LANE_GAP_PX;
}
