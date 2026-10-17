import type { EventTreeListResponse } from "@/api/narrativeTypes";

export const MARKER_RADIUS = 6;
export const CONTENT_GAP = 16;
const MARKER_PITCH = 30;
const ANCHOR_PITCH = 188;
const OUTCOME_TOP = 12;

export interface TitleBox { left: number; top: number; width: number; height: number }
export interface EventMarkPosition { x: number; y: number; left: number; top: number; width: number; height: number; titleBox: TitleBox; column: number; stackIndex: number }
export interface OutcomeBox { x: number; left: number; top: number; width: number; height: number }
export interface ArcAnchor { x: number; y: number; width: number }
export interface EventTreeLayoutResult { positions: Map<string, EventMarkPosition>; outcomeBoxes: Map<string, OutcomeBox>; arcAnchors: Map<string, ArcAnchor>; width: number; height: number; outcomeBandBottom: number; anchorRowY: number }

/** 固定阅读字号的文本度量，不随窗口缩放文字 */
export function measureTextWidth(text: string, fontSize: number): number {
  return [...text].reduce((sum, char) => sum + ((char.codePointAt(0) ?? 0) > 0x2e7f ? fontSize : fontSize * 0.55), 0);
}
const average = (values: number[], fallback: number) => values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : fallback;

/** 按正文顺序划分连续阅读区域；区内使用全部真实关联定位，章节不参与空间分组 */
export function eventTreeLayout(book: EventTreeListResponse, availableWidth: number, availableHeight: number): EventTreeLayoutResult {
  const height = availableHeight;
  // 页面底部已有 8px 留白，锚点圆心至桌面视口底部合计保留约 149px
  const anchorRowY = Math.min(height - 70, Math.max(170, height - 149 + 8));
  const outcomeBandBottom = OUTCOME_TOP + 48 + 58;
  const middleTop = outcomeBandBottom + CONTENT_GAP;
  const middleBottom = anchorRowY - 36;
  const verticalCapacity = Math.max(2, Math.floor((middleBottom - middleTop) / MARKER_PITCH));
  const events = [...book.events].sort((a, b) => (a.first_text_position ?? Infinity) - (b.first_text_position ?? Infinity) || a.event_id.localeCompare(b.event_id));
  const rank = new Map(events.map((event, index) => [event.event_id, index]));
  const arcsByEvent = new Map<string, string[]>();
  const outcomesByEvent = new Map<string, string[]>();
  const add = (map: Map<string, string[]>, eventId: string, id: string) => {
    const values = map.get(eventId) ?? [];
    if (!values.includes(id)) values.push(id);
    map.set(eventId, values);
  };
  book.event_arc_links.forEach(link => add(arcsByEvent, link.event_id, link.arc_id));
  book.event_outcome_links.forEach(link => add(outcomesByEvent, link.event_id, link.outcome_id));
  const earliestArc = (arcId: string) => Math.min(Infinity, ...book.event_arc_links.filter(link => link.arc_id === arcId).map(link => rank.get(link.event_id) ?? Infinity));
  const earliestOutcome = (outcomeId: string) => Math.min(Infinity, ...book.event_outcome_links.filter(link => link.outcome_id === outcomeId).map(link => rank.get(link.event_id) ?? Infinity));
  const arcs = [...book.arcs].sort((a, b) => earliestArc(a.arc_id) - earliestArc(b.arc_id) || a.arc_id.localeCompare(b.arc_id));
  const outcomes = [...book.outcomes].sort((a, b) => earliestOutcome(a.outcome_id) - earliestOutcome(b.outcome_id) || (a.first_text_position ?? Infinity) - (b.first_text_position ?? Infinity) || a.outcome_id.localeCompare(b.outcome_id));
  // 以固定标记间距确定区域容量；线数和结果数增长时扩展横向，不把它们压成七个槽位
  const arcWidths = arcs.map(arc => Math.min(200, Math.max(110, measureTextWidth(arc.title, 16), measureTextWidth(arc.objective, 13))));
  const outcomeWidths = outcomes.map(outcome => Math.min(154, Math.max(100, measureTextWidth(outcome.title, 16), measureTextWidth(outcome.description, 13))));
  const edgeInset = Math.max(0, ...arcWidths, ...outcomeWidths) / 2 + CONTENT_GAP;
  const outcomePitch = Math.max(100, ...outcomeWidths) + CONTENT_GAP;
  const regionWidth = Math.max(availableWidth, (arcs.length - 1) * ANCHOR_PITCH + edgeInset * 2, (outcomes.length - 1) * outcomePitch + edgeInset * 2);
  // 容量来自固定点击标记可占用的二维槽位；同结果可局部避让为相邻短列，不因标题列数制造空尾屏
  const contentColumns = Math.max(1, Math.floor((regionWidth - edgeInset * 2) / MARKER_PITCH));
  const regionCapacity = verticalCapacity * contentColumns;
  const regionCount = Math.max(1, Math.ceil(events.length / regionCapacity));
  const slot = (index: number, count: number) => count < 2 ? regionWidth / 2 : edgeInset + index * (regionWidth - edgeInset * 2) / (count - 1);
  const arcAnchors = new Map<string, ArcAnchor>();
  for (const [index, arc] of arcs.entries()) {
    const first = earliestArc(arc.arc_id);
    const region = Number.isFinite(first) ? Math.floor(first / regionCapacity) : 0;
    const width = arcWidths[index];
    arcAnchors.set(arc.arc_id, { x: region * regionWidth + slot(index, arcs.length), y: anchorRowY, width });
  }
  const outcomeBoxes = new Map<string, OutcomeBox>();
  for (const [index, outcome] of outcomes.entries()) {
    const first = earliestOutcome(outcome.outcome_id);
    const region = Number.isFinite(first) ? Math.floor(first / regionCapacity) : 0;
    const x = region * regionWidth + slot(index, outcomes.length);
    const width = outcomeWidths[index];
    // 正文位置只影响标题的局部起点，不改写事实关系或制造事件归属
    const top = OUTCOME_TOP + (index % 3) * 24;
    outcomeBoxes.set(outcome.outcome_id, { x, left: x - width / 2, top, width, height: 58 });
  }
  const positions = new Map<string, EventMarkPosition>();
  const placed: EventMarkPosition[] = [];
  for (const [index, event] of events.entries()) {
    const region = Math.floor(index / regionCapacity);
    const start = region * regionCapacity;
    const count = Math.min(regionCapacity, events.length - start);
    const progress = count > 1 ? (index - start) / (count - 1) : 0.5;
    const localAnchorXs = (arcsByEvent.get(event.event_id) ?? []).map(id => arcAnchors.get(id)?.x).filter((x): x is number => x != null).map(x => x % regionWidth);
    const localOutcomeXs = (outcomesByEvent.get(event.event_id) ?? []).map(id => outcomeBoxes.get(id)?.x).filter((x): x is number => x != null).map(x => x % regionWidth);
    const from = average(localAnchorXs, slot(index - start, count));
    const to = average(localOutcomeXs, from);
    // 所有关联平等参与几何中点，事件身份不因多线或多结果被复制
    const centerX = region * regionWidth + to;
    let x = centerX;
    const y = middleBottom - progress * (middleBottom - middleTop);
    // 按真实28px点击矩形避让；可用槽位决定尝试数，不让密集单结果被固定16次上限截断
    const overlaps = (candidate: number) => placed.some(point => Math.abs(point.y - y) < 28 && Math.abs(point.x - candidate) < 28);
    for (let attempt = 0; overlaps(x) && attempt < contentColumns * 2 + 2; attempt++) {
      const shift = (Math.floor(attempt / 2) + 1) * MARKER_PITCH * (attempt % 2 ? -1 : 1);
      x = Math.min((region + 1) * regionWidth - 18, Math.max(region * regionWidth + 18, centerX + shift));
    }
    // 已有局部槽位确实占满时才继续横向延伸，保留固定阅读尺寸和唯一事件身份
    if (overlaps(x)) {
      x = (region + 1) * regionWidth + MARKER_PITCH;
      while (overlaps(x)) x += MARKER_PITCH;
    }
    const titleWidth = Math.min(150, Math.max(40, measureTextWidth(event.title, 13)));
    const point: EventMarkPosition = { x, y, left: x - 14, top: y - 14, width: 28, height: 28, titleBox: { left: x + 14, top: y - 10, width: titleWidth, height: 20 }, column: region, stackIndex: index - start };
    positions.set(event.event_id, point); placed.push(point);
  }
  const right = Math.max(regionCount * regionWidth, ...[...positions.values()].map(position => position.x + 14 + CONTENT_GAP), ...[...outcomeBoxes.values()].map(box => box.left + box.width + CONTENT_GAP), ...[...arcAnchors.values()].map(anchor => anchor.x + anchor.width / 2 + CONTENT_GAP));
  return { positions, outcomeBoxes, arcAnchors, width: right, height, outcomeBandBottom, anchorRowY };
}
