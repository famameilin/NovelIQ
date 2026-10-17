import type { EventTreeListResponse } from "@/api/narrativeTypes";
import { MARKER_RADIUS, type EventTreeLayoutResult } from "./eventTreeLayout";

/** 画布曲线：端点停在标记边缘端口，同向同端点合并、反向独立 */
export interface EventTreeCurve {
  d: string;
  kinds: string[];
  relationIds: string[];
  sourceId: string;
  targetId: string;
  channel: "arc" | "outcome" | "relation";
}

/** 两端都在屏外时仍保留跨越视口的路径；所有控制点均在端点横向区间内 */
export function curveCrossesWindow(sourceX: number, targetX: number, left: number, right: number): boolean {
  return Math.min(sourceX, targetX) - MARKER_RADIUS <= right && Math.max(sourceX, targetX) + MARKER_RADIUS >= left;
}

/** 叙事线锚点处的多条细曲线局部汇拢后扇形分流，端点保持纵向切线接入标记底缘 */
function anchorToEvent(anchor: { x: number; y: number }, event: { x: number; y: number }): string {
  const ay = anchor.y, ey = event.y + MARKER_RADIUS;
  const spread = ay - ey;
  return `M ${anchor.x} ${ay} C ${anchor.x} ${ay - spread * 0.65}, ${event.x} ${ey + spread * 0.38}, ${event.x} ${ey}`;
}

/** 事件到结果：从标记顶缘纵向接入结果说明的完整底缘，不穿过文字 */
function eventToOutcome(event: { x: number; y: number }, outcome: { x: number; bottom: number }): string {
  const ey = event.y - MARKER_RADIUS, oy = outcome.bottom;
  const spread = ey - oy;
  return `M ${event.x} ${ey} C ${event.x} ${ey - spread * 0.38}, ${outcome.x} ${oy + spread * 0.21}, ${outcome.x} ${oy}`;
}

/** 大事件之间的真实关系：按相对位置选择边缘端口，保持平滑曲线 */
function eventToEvent(source: { x: number; y: number }, target: { x: number; y: number }): string {
  const dy = target.y - source.y, dx = target.x - source.x;
  if (dy < -40) {
    const sy = source.y - MARKER_RADIUS, ty = target.y + MARKER_RADIUS;
    return `M ${source.x} ${sy} C ${source.x} ${sy + dy * 0.45}, ${target.x} ${ty - dy * 0.45}, ${target.x} ${ty}`;
  }
  if (dy > 40) {
    const sy = source.y + MARKER_RADIUS, ty = target.y - MARKER_RADIUS;
    return `M ${source.x} ${sy} C ${source.x} ${sy + dy * 0.45}, ${target.x} ${ty - dy * 0.45}, ${target.x} ${ty}`;
  }
  const sign = dx >= 0 ? 1 : -1;
  const sx = source.x + sign * MARKER_RADIUS, tx = target.x - sign * MARKER_RADIUS;
  return `M ${sx} ${source.y} C ${sx + dx * 0.45} ${source.y}, ${tx - dx * 0.45} ${target.y}, ${tx} ${target.y}`;
}

export function eventTreeCurves(book: EventTreeListResponse, layout: EventTreeLayoutResult): EventTreeCurve[] {
  const curves: EventTreeCurve[] = [];

  // 事件—叙事线：同一事件与同一叙事线的多条关联合并为一条，角色聚合保留
  const arcLinks = new Map<string, { arc_id: string; event_id: string; roles: string[] }>();
  for (const link of book.event_arc_links) {
    const key = `${link.arc_id}→${link.event_id}`;
    const entry = arcLinks.get(key) ?? { arc_id: link.arc_id, event_id: link.event_id, roles: [] };
    if (link.role && !entry.roles.includes(link.role)) entry.roles.push(link.role);
    arcLinks.set(key, entry);
  }
  for (const link of arcLinks.values()) {
    const anchor = layout.arcAnchors.get(link.arc_id), position = layout.positions.get(link.event_id);
    if (!anchor || !position) continue;
    curves.push({ d: anchorToEvent(anchor, position), kinds: link.roles.length ? link.roles : ["叙事线关联"], relationIds: [`arc:${link.arc_id}:${link.event_id}`], sourceId: link.arc_id, targetId: link.event_id, channel: "arc" });
  }

  // 事件—结果：多对多关联逐项保留依据，同一对端点合并绘制
  const outcomeLinks = new Set<string>();
  for (const link of book.event_outcome_links) outcomeLinks.add(`${link.event_id}→${link.outcome_id}`);
  for (const key of outcomeLinks) {
    const [eventId, outcomeId] = key.split("→");
    const position = layout.positions.get(eventId), box = layout.outcomeBoxes.get(outcomeId);
    if (!position || !box) continue;
    curves.push({ d: eventToOutcome(position, { x: box.x, bottom: box.top + box.height }), kinds: ["结果关联"], relationIds: [`outcome:${outcomeId}:${eventId}`], sourceId: eventId, targetId: outcomeId, channel: "outcome" });
  }

  // 真实关系：只绘制两端都有展示身份的大事件；同向同端点合并，反向关系保持独立
  const grouped = new Map<string, { source_id: string; target_id: string; kinds: string[]; ids: string[] }>();
  book.relations.forEach((relation, index) => {
    if (relation.source_kind !== "event" || relation.target_kind !== "event" || relation.source_id === relation.target_id) return;
    const key = `${relation.source_id}→${relation.target_id}`;
    const entry = grouped.get(key) ?? { source_id: relation.source_id, target_id: relation.target_id, kinds: [], ids: [] };
    if (!entry.kinds.includes(relation.relation_type)) entry.kinds.push(relation.relation_type);
    entry.ids.push(`relation:${index}`);
    grouped.set(key, entry);
  });
  for (const relation of grouped.values()) {
    const source = layout.positions.get(relation.source_id), target = layout.positions.get(relation.target_id);
    if (!source || !target) continue;
    curves.push({ d: eventToEvent(source, target), kinds: relation.kinds, relationIds: relation.ids, sourceId: relation.source_id, targetId: relation.target_id, channel: "relation" });
  }
  return curves;
}
