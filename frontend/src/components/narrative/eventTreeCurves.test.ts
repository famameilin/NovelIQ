import { expect, it } from "vitest";
import type { EventTreeListResponse } from "@/api/narrativeTypes";
import { MARKER_RADIUS, eventTreeLayout } from "./eventTreeLayout";
import { curveCrossesWindow, eventTreeCurves } from "./eventTreeCurves";

function bookWith(relations: EventTreeListResponse["relations"]): EventTreeListResponse {
  return {
    run_id: "run-curve",
    chapters: [{ chapter_id: 1, title: "第 1 章", chapter_order: 1 }],
    counts: { top_level_events: 2, child_events: 0, all_events: 2, outcomes: 1, event_outcome_links: 1, arcs: 1, event_arc_links: 2, relations: relations.length, foreshadowing_actions: 0 },
    arcs: [{ arc_id: "arc-1", parent_arc_id: null, kind: "main", title: "主线", objective: "目标" }],
    events: [
      { event_id: "ev-1", title: "前事", summary: "", from: 1, to: 1, event_type: "推进", status: "进行中", first_text_position: 100, chapter_id: 1, chapter_order: 1 },
      { event_id: "ev-2", title: "后事", summary: "", from: 1, to: 1, event_type: "推进", status: "进行中", first_text_position: 900, chapter_id: 1, chapter_order: 1 },
    ],
    outcomes: [{ outcome_id: "oc-1", title: "结果", description: "说明", first_text_position: 500 }],
    event_arc_links: [
      { event_id: "ev-1", arc_id: "arc-1", role: "推进", reason: "依据" },
      { event_id: "ev-1", arc_id: "arc-1", role: "转折", reason: "依据" },
      { event_id: "ev-2", arc_id: "arc-1", role: "推进", reason: "依据" },
    ],
    event_outcome_links: [{ event_id: "ev-1", outcome_id: "oc-1", reason: "依据" }],
    relations,
    foreshadowing_actions: [],
    next_cursor: null,
  };
}

const book = bookWith([
  { source_kind: "event", source_id: "ev-1", target_kind: "event", target_id: "ev-2", relation_type: "causal", reason: "依据" },
  { source_kind: "event", source_id: "ev-1", target_kind: "event", target_id: "ev-2", relation_type: "reference", reason: "依据" },
  { source_kind: "event", source_id: "ev-2", target_kind: "event", target_id: "ev-1", relation_type: "foreshadowing", reason: "依据" },
  { source_kind: "event", source_id: "child-event", target_kind: "event", target_id: "ev-2", relation_type: "causal", reason: "依据", top_level_event_id: "ev-1" },
]);
const layout = eventTreeLayout(book, 1000, 650);
const curves = eventTreeCurves(book, layout);
const numbers = (d: string) => d.match(/-?\d+\.?\d*/g)!.map(Number);

it("同向同端点的多种关系合并为一条曲线并聚合类型", () => {
  const merged = curves.filter(curve => curve.channel === "relation" && curve.sourceId === "ev-1" && curve.targetId === "ev-2");
  expect(merged).toHaveLength(1);
  expect(merged[0].kinds).toEqual(["causal", "reference"]);
  expect(merged[0].relationIds).toHaveLength(2);
});

it("反向关系保持独立，非顶层事件端点不产生画布曲线", () => {
  expect(curves.filter(curve => curve.channel === "relation" && curve.sourceId === "ev-2" && curve.targetId === "ev-1")).toHaveLength(1);
  expect(curves.some(curve => curve.relationIds.some(id => id === "relation:3"))).toBe(false);
  expect(curves.some(curve => curve.sourceId === "child-event")).toBe(false);
});

it("同一事件与同一叙事线的多重角色合并绘制", () => {
  const arcCurves = curves.filter(curve => curve.channel === "arc" && curve.targetId === "ev-1");
  expect(arcCurves).toHaveLength(1);
  expect(arcCurves[0].kinds).toEqual(["推进", "转折"]);
});

it("多线多结果的大事件只占一个位置且保留所有实际路径", () => {
  const multi = bookWith([]);
  multi.arcs.push({ ...multi.arcs[0], arc_id: "arc-2" });
  multi.outcomes.push({ ...multi.outcomes[0], outcome_id: "oc-2" });
  multi.event_arc_links.push({ event_id: "ev-1", arc_id: "arc-2", role: "推进", reason: "第二真实线" });
  multi.event_outcome_links.push({ event_id: "ev-1", outcome_id: "oc-2", reason: "第二真实结果" });
  const multiLayout = eventTreeLayout(multi, 1000, 650);
  const multiCurves = eventTreeCurves(multi, multiLayout);
  expect([...multiLayout.positions.keys()].filter(id => id === "ev-1")).toHaveLength(1);
  expect(multiCurves.filter(curve => curve.channel === "arc" && curve.targetId === "ev-1")).toHaveLength(2);
  expect(multiCurves.filter(curve => curve.channel === "outcome" && curve.sourceId === "ev-1")).toHaveLength(2);
});

it("叙事线曲线端点停在锚点圆心与标记底缘，不穿过标题文字", () => {
  const curve = curves.find(item => item.channel === "arc" && item.targetId === "ev-1")!;
  const anchor = layout.arcAnchors.get("arc-1")!;
  const position = layout.positions.get("ev-1")!;
  const [sx, sy, , , , , ex, ey] = numbers(curve.d);
  expect([sx, sy]).toEqual([anchor.x, anchor.y]);
  expect(ex).toBe(position.x);
  expect(ey).toBe(position.y + MARKER_RADIUS);
});

it("两端位于屏外但跨过视口的真实曲线仍绘制", () => {
  expect(curveCrossesWindow(-200, 1400, 0, 1000)).toBe(true);
  expect(curveCrossesWindow(1400, -200, 0, 1000)).toBe(true);
  expect(curveCrossesWindow(-200, -50, 0, 1000)).toBe(false);
  expect(curveCrossesWindow(1100, 1400, 0, 1000)).toBe(false);
});

it("结果曲线从标记顶缘接入结果说明底缘", () => {
  const curve = curves.find(item => item.channel === "outcome")!;
  const box = layout.outcomeBoxes.get("oc-1")!;
  const position = layout.positions.get("ev-1")!;
  const [sx, sy, , , , , ex, ey] = numbers(curve.d);
  expect([sx, sy]).toEqual([position.x, position.y - MARKER_RADIUS]);
  expect([ex, ey]).toEqual([box.x, box.top + box.height]);
});

it("短距离连接仍在两端之间上行，不回绕到叙事线锚点下方", () => {
  for (const curve of curves.filter(item => item.channel !== "relation")) {
    const [, startY, , control1Y, , control2Y, , endY] = numbers(curve.d);
    expect(control1Y).toBeGreaterThanOrEqual(Math.min(startY, endY));
    expect(control1Y).toBeLessThanOrEqual(Math.max(startY, endY));
    expect(control2Y).toBeGreaterThanOrEqual(Math.min(startY, endY));
    expect(control2Y).toBeLessThanOrEqual(Math.max(startY, endY));
  }
});
