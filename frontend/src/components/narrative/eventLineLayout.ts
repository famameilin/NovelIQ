import { eventDisplayKey } from "@/api/eventQueues";
import type { EventLine, EventLineBook, EventLineNode } from "./eventLines";
import { eventLineColor } from "./presentation";

export const EVENT_LINE_MIN_WIDTH = 1170;
/** 左侧叙事线导轨宽度，容纳颜色条、线名与事件数 */
export const RAIL_WIDTH = 236;
const RAIL_BAR_X = 37;
const RAIL_BAR_WIDTH = 6;
const RAIL_NAME_X = 54;
/** 事件树轨道的起点，紧跟导轨后留出首个节点标签的宽度 */
const TRACK_START_X = 306;
/** 相邻事件树节点的横向间距，节点标签在此间距内完整显示 */
export const NODE_GAP = 128;
export const ROW_TOP = 84;
/** 行距在可用高度内自适应，节点多时保持最小行距 */
export const ROW_PITCH_MIN = 44;
export const ROW_PITCH_MAX = 120;
const ROW_BOTTOM = 32;
const TRACK_END_PAD = 60;

export interface PlacedLineNode {
  line: EventLine;
  node: EventLineNode;
  x: number;
  y: number;
  size: number;
  labelY: number;
  labelVisible: boolean;
}

export interface PlacedLine {
  line: EventLine;
  y: number;
  color: string;
  /** 本线事件树轨道，从轨道起点到最后一个节点 */
  path: string;
  /** 穿过整幅画布的浅色导轨 */
  guide: string;
  nodes: PlacedLineNode[];
  end: { x: number; y: number };
}

export interface EventLineLayoutResult {
  width: number;
  height: number;
  rail: { width: number; nameX: number; barX: number; barWidth: number };
  trackStart: number;
  rowPitch: number;
  lines: PlacedLine[];
  nodeByEvent: Map<string, PlacedLineNode>;
  pointByEvent: Map<string, { x: number; y: number; lineId: string }>;
}

function hashFraction(id: string): number {
  let hash = 2166136261;
  for (let index = 0; index < id.length; index++) {
    hash ^= id.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return ((hash >>> 0) % 1000) / 1000;
}

/** 每条叙事线占用一行：左侧导轨给出线名与事件数，右侧按顺序排开本线的事件树节点 */
export function eventLineLayout(book: EventLineBook, width: number, height: number): EventLineLayoutResult {
  const rowCount = Math.max(1, book.lines.length);
  const available = height - ROW_TOP - ROW_BOTTOM;
  const rowPitch = Math.min(ROW_PITCH_MAX, Math.max(ROW_PITCH_MIN, available / rowCount));
  // 行距到达上限后整块居中，避免底部留下大块空白
  const blockTop = ROW_TOP + Math.max(0, (available - rowPitch * rowCount) / 2);
  const canvasHeight = Math.max(320, height, ROW_TOP + rowPitch * rowCount + ROW_BOTTOM);
  const maxNodes = book.lines.reduce((max, line) => Math.max(max, line.nodes.length), 1);
  const canvasWidth = Math.max(EVENT_LINE_MIN_WIDTH, width, TRACK_START_X + (maxNodes - 1) * NODE_GAP + TRACK_END_PAD);
  const nodeByEvent = new Map<string, PlacedLineNode>();
  const pointByEvent = new Map<string, { x: number; y: number; lineId: string }>();
  const lines = book.lines.map((line, index) => {
    const y = blockTop + index * rowPitch + rowPitch / 2;
    const nodes = line.nodes.map((node, position) => {
      const x = TRACK_START_X + position * NODE_GAP;
      const size = 8 + Math.min(6, Math.sqrt(node.eventIds.length));
      const placed = { line, node, x, y, size, labelY: y - (size / 2 + 5), labelVisible: true };
      nodeByEvent.set(eventDisplayKey(line.id, node.eventId), placed);
      pointByEvent.set(eventDisplayKey(line.id, node.eventId), { x, y, lineId: line.id });
      return placed;
    });
    const lastX = nodes.length > 0 ? nodes.at(-1)!.x + hashFraction(`${line.id}:end`) * 8 : TRACK_START_X;
    const path = `M ${TRACK_START_X} ${y} L ${lastX} ${y}`;
    const guide = `M ${TRACK_START_X} ${y} L ${canvasWidth - 24} ${y}`;
    return { line, y, color: eventLineColor(line.id, line.colorIndex), path, guide, nodes, end: { x: lastX, y } };
  });
  // 关键事件标签只在互不重叠时显示，重复文案让位给左侧导轨
  const labelBoxes: Array<{ left: number; right: number; top: number; bottom: number }> = [];
  for (const placed of lines) {
    for (const node of placed.nodes) {
      if (node.node.isRoot && placed.nodes.some(item => !item.node.isRoot)) {
        node.labelVisible = false;
        continue;
      }
      const labelWidth = Math.min(108, node.node.displayTitle.length * 12 + 8);
      const left = node.x - labelWidth / 2;
      const right = node.x + labelWidth / 2;
      const top = node.labelY - 16;
      const bottom = node.labelY;
      const overlaps = labelBoxes.some(box =>
        left < box.right + 6 && right > box.left - 6 && top < box.bottom + 3 && bottom > box.top - 3);
      if (overlaps) node.labelVisible = false;
      else labelBoxes.push({ left, right, top, bottom });
    }
  }
  return {
    width: canvasWidth,
    height: canvasHeight,
    rail: { width: RAIL_WIDTH, nameX: RAIL_NAME_X, barX: RAIL_BAR_X, barWidth: RAIL_BAR_WIDTH },
    trackStart: TRACK_START_X,
    rowPitch,
    lines,
    nodeByEvent,
    pointByEvent,
  };
}
