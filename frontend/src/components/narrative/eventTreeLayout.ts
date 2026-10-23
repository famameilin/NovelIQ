import type { EventTreeListResponse } from "@/api/narrativeTypes";

export const MARKER_RADIUS = 6;
export const CONTENT_GAP = 16;
export const OUTCOME_STEM_GAP = 14;
const MARKER_PITCH = 34;
const CAPTION_GAP = CONTENT_GAP;
const OUTCOME_TOP = 12;

export interface TitleBox { left: number; top: number; width: number; height: number }
export interface EventMarkPosition { x: number; y: number; left: number; top: number; width: number; height: number; titleBox: TitleBox; column: number; stackIndex: number }
export interface OutcomeBox { x: number; left: number; top: number; width: number; height: number }
export interface ArcAnchor { x: number; y: number; width: number }
export interface EventTreeLayoutResult { positions: Map<string, EventMarkPosition>; outcomeBoxes: Map<string, OutcomeBox>; arcAnchors: Map<string, ArcAnchor>; width: number; height: number; outcomeBandBottom: number; anchorRowY: number }

/** 固定阅读字号的文本度量，不随窗口缩放文字 */
export function measureTextWidth(text: string, fontSize: number): number {
  return [...text].reduce((sum, char) => sum + (/^[\x20-\x7e]$/.test(char) ? fontSize * 0.55 : fontSize), 0);
}
const average = (values: number[], fallback: number) => values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : fallback;

/** 完整标题和说明参与尺寸计算，长说明通过横向扩展限制纵向占用 */
function captionSize(title: string, description: string) {
  const width = Math.max(110, Math.min(200, Math.max(measureTextWidth(title, 16), measureTextWidth(description, 13))), measureTextWidth(title, 16) * 1.05 / 2 + 12, measureTextWidth(description, 13) / 4 + 16);
  const lines = (text: string, fontSize: number) => text.split("\n").reduce((sum, line) => sum + Math.max(1, Math.ceil(measureTextWidth(line, fontSize) / width)), 0);
  return { width, height: lines(title, 16) * 22 + 4 + lines(description, 13) * 18 };
}

/** 正文顺序决定局部纵向阅读顺序，真实端点决定横向位置 */
export function eventTreeLayout(book: EventTreeListResponse, availableWidth: number, availableHeight: number): EventTreeLayoutResult {
  const height = availableHeight;
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
  const arcSizes = arcs.map(arc => captionSize(arc.title, arc.objective));
  const outcomeSizes = outcomes.map(outcome => captionSize(outcome.title, outcome.description));
  const edgeInset = Math.max(0, ...arcSizes.map(size => size.width), ...outcomeSizes.map(size => size.width)) / 2 + CONTENT_GAP;
  const rowWidth = (sizes: typeof arcSizes) => Math.max(0, sizes.length - 1) * (Math.max(0, ...sizes.map(size => size.width)) + CAPTION_GAP) + edgeInset * 2;
  const regionWidth = Math.max(availableWidth, rowWidth(arcSizes), rowWidth(outcomeSizes));
  const rowCenters = (sizes: typeof arcSizes) => sizes.map((_, index) => sizes.length < 2 ? regionWidth / 2 : edgeInset + index * (regionWidth - edgeInset * 2) / (sizes.length - 1));
  const anchorRowY = height - Math.max(141, 12 + 16 + Math.max(0, ...arcSizes.map(size => size.height)) + CONTENT_GAP);
  const arcAnchors = new Map<string, ArcAnchor>();
  const arcXs = rowCenters(arcSizes);
  arcs.forEach((arc, index) => arcAnchors.set(arc.arc_id, { x: arcXs[index], y: anchorRowY, width: arcSizes[index].width }));
  const outcomeBoxes = new Map<string, OutcomeBox>();
  const outcomeXs = rowCenters(outcomeSizes);
  outcomes.forEach((outcome, index) => {
    const size = outcomeSizes[index], x = outcomeXs[index];
    outcomeBoxes.set(outcome.outcome_id, { x, left: x - size.width / 2, top: OUTCOME_TOP + (index % 3) * 24, ...size });
  });
  const outcomeBandBottom = Math.max(OUTCOME_TOP, ...[...outcomeBoxes.values()].map(box => box.top + box.height));
  const middleTop = outcomeBandBottom + CONTENT_GAP + OUTCOME_STEM_GAP;
  const middleBottom = anchorRowY - 36;
  const verticalCapacity = Math.max(2, Math.floor((middleBottom - middleTop) / MARKER_PITCH) + 1);
  const unlinked = events.filter(event => !arcsByEvent.has(event.event_id) && !outcomesByEvent.has(event.event_id));
  const linked = events.filter(event => arcsByEvent.has(event.event_id) || outcomesByEvent.has(event.event_id));
  const linkedRank = new Map(linked.map((event, index) => [event.event_id, index]));
  const continuous = linked.length > verticalCapacity;
  const unlinkedRank = new Map(unlinked.map((event, index) => [event.event_id, index]));
  const neutralColumns = Math.max(1, Math.ceil(unlinked.length / verticalCapacity));
  const groups = new Map<number, typeof events>();
  for (const event of events) {
    const anchorXs = (arcsByEvent.get(event.event_id) ?? []).flatMap(id => arcAnchors.has(id) ? [arcAnchors.get(id)!.x] : []);
    const resultXs = (outcomesByEvent.get(event.event_id) ?? []).flatMap(id => outcomeBoxes.has(id) ? [outcomeBoxes.get(id)!.x] : []);
    const neutralColumn = Math.floor((unlinkedRank.get(event.event_id) ?? 0) / verticalCapacity);
    // 中性标记只按正文划分阅读短列，不生成线归属或连接
    const fallback = CONTENT_GAP + 14 + (neutralColumn + 0.5) * (regionWidth - CONTENT_GAP * 2 - 28) / neutralColumns;
    const center = average(resultXs, average(anchorXs, fallback));
    const group = groups.get(center) ?? [];
    group.push(event);
    groups.set(center, group);
  }
  const positions = new Map<string, EventMarkPosition>();
  const placed: EventMarkPosition[] = [];
  for (const [groupIndex, [center, group]] of [...groups].sort(([a], [b]) => a - b).entries()) {
    const columns = Math.ceil(group.length / verticalCapacity);
    const perColumn = Math.ceil(group.length / columns);
    for (const [index, event] of group.entries()) {
      const column = Math.floor(index / perColumn), stackIndex = index % perColumn;
      const count = Math.min(perColumn, group.length - column * perColumn);
      const progress = count > 1 ? stackIndex / (count - 1) : 0.5;
      const localBottom = middleBottom - (groupIndex % 3) * 12;
      const localTop = middleTop + ((groupIndex + column) % 4) * 14;
      const localHeight = Math.max(0, localBottom - localTop);
      const occupiedHeight = Math.min(localHeight, Math.max(0, count - 1) * MARKER_PITCH);
      const order = linkedRank.get(event.event_id);
      const continuousPosition = continuous && order != null;
      const y = continuousPosition ? middleBottom - order / Math.max(1, linked.length - 1) * (middleBottom - middleTop) : localBottom - (localHeight - occupiedHeight) / 2 - progress * occupiedHeight;
      const idealX = center + (continuousPosition ? 0 : (column - (columns - 1) / 2) * MARKER_PITCH);
      let x = Math.max(CONTENT_GAP + 14, Math.min(regionWidth - CONTENT_GAP - 14, idealX));
      const overlaps = (candidate: number) => placed.some(point => Math.abs(point.y - y) < 28 && Math.abs(point.x - candidate) < 28);
      let attempt = 0;
      while (overlaps(x)) {
        const shift = (Math.floor(attempt / 2) + 1) * (continuousPosition ? 28 : MARKER_PITCH) * (attempt % 2 ? -1 : 1);
        x = Math.max(CONTENT_GAP + 14, idealX + shift);
        attempt++;
      }
      const titleWidth = Math.max(40, measureTextWidth(event.title, 13));
      const point: EventMarkPosition = { x, y, left: x - 14, top: y - 14, width: 28, height: 28, titleBox: { left: x + 14, top: y - 10, width: titleWidth, height: 20 }, column: Math.floor(x / regionWidth), stackIndex };
      positions.set(event.event_id, point);
      placed.push(point);
    }
  }
  const right = Math.max(regionWidth, ...placed.map(position => position.x + 14 + CONTENT_GAP));
  return { positions, outcomeBoxes, arcAnchors, width: right, height, outcomeBandBottom, anchorRowY };
}
