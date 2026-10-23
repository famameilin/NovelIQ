import { expect, it } from "vitest";
import { CONTENT_GAP, MARKER_RADIUS, eventTreeLayout } from "./eventTreeLayout";

import { buildScaleBook } from "@/mocks/eventTreeScale";

const FRAME = { width: 1000, height: 650 };

it("同一输入永远得到同一输出", () => {
  const book = buildScaleBook({ chapters: 6, eventsPerChapter: 4, arcs: 5, outcomes: 4 });
  const first = eventTreeLayout(book, FRAME.width, FRAME.height);
  const second = eventTreeLayout(book, FRAME.width, FRAME.height);
  const dump = (layout: typeof first) => JSON.stringify({
    positions: [...layout.positions.entries()],
    outcomes: [...layout.outcomeBoxes.entries()],
    anchors: [...layout.arcAnchors.entries()],
    width: layout.width,
  });
  expect(dump(first)).toBe(dump(second));
});

it("跨章连续保持正文纵向顺序，不在章边界重置为新列", () => {
  const book = buildScaleBook({ chapters: 3, eventsPerChapter: 3, arcs: 1, outcomes: 1 });
  const layout = eventTreeLayout(book, FRAME.width, FRAME.height);
  const [a, b, c] = ["ev-1-0", "ev-1-1", "ev-1-2"].map(id => layout.positions.get(id)!);
  // 同章同列，正文顺序靠后的在上方（y 更小）
  expect(a.column).toBe(b.column);
  expect(b.column).toBe(c.column);
  expect(a.y).toBeGreaterThan(b.y);
  expect(b.y).toBeGreaterThan(c.y);
  expect(a.stackIndex).toBe(0);
  expect(c.stackIndex).toBe(2);
  // 章边界继续同一阅读区域，不生成独立章节列
  const next = layout.positions.get("ev-2-0")!;
  expect(next.column).toBe(c.column);
  expect(next.y).toBeLessThan(c.y);
  const changedChapters = { ...book, events: book.events.map(event => ({ ...event, chapter_id: 99, chapter_order: 99 })) };
  expect([...eventTreeLayout(changedChapters, FRAME.width, FRAME.height).positions]).toEqual([...layout.positions]);
});

it("纵向边界落在可用画布高度内，上下相邻内容至少保留 16px", () => {
  const book = buildScaleBook({ chapters: 4, eventsPerChapter: 6, arcs: 3, outcomes: 3 });
  const layout = eventTreeLayout(book, FRAME.width, FRAME.height);
  expect(layout.height).toBe(FRAME.height);
  for (const position of layout.positions.values()) {
    expect(position.y).toBeGreaterThanOrEqual(layout.outcomeBandBottom + CONTENT_GAP - 0.01);
    expect(position.y + MARKER_RADIUS).toBeLessThanOrEqual(layout.anchorRowY - CONTENT_GAP + 0.01);
  }
  const points = [...layout.positions.values()];
  for (let index = 0; index < points.length; index++) for (const other of points.slice(index + 1)) {
    // 常驻标题已移除，验证实际点击标记之间的空间而非旧标题表格
    expect(Math.abs(points[index].x - other.x) >= 28 || Math.abs(points[index].y - other.y) >= 28).toBe(true);
  }
});

it("每条叙事线只有一个锚点，结果横向延伸时画布宽度覆盖完整内容", () => {
  const book = buildScaleBook({ chapters: 8, eventsPerChapter: 3, arcs: 12, outcomes: 14 });
  const layout = eventTreeLayout(book, FRAME.width, FRAME.height);
  expect(layout.arcAnchors.size).toBe(12);
  expect(layout.outcomeBoxes.size).toBe(14);
  expect(layout.width).toBeGreaterThan(FRAME.width);
  for (const anchor of layout.arcAnchors.values()) {
    expect(anchor.x - anchor.width / 2).toBeGreaterThanOrEqual(CONTENT_GAP);
    expect(anchor.x + anchor.width / 2).toBeLessThanOrEqual(layout.width - 0.01);
  }
  for (const box of layout.outcomeBoxes.values()) {
    expect(box.left).toBeGreaterThanOrEqual(CONTENT_GAP);
    expect(box.left + box.width).toBeLessThanOrEqual(layout.width - 0.01);
    expect(box.top).toBeGreaterThanOrEqual(0);
  }
});

it.each([
  { name: "30 章当量", options: { chapters: 30, eventsPerChapter: 4, arcs: 7, outcomes: 9 } },
  { name: "100 章当量", options: { chapters: 100, eventsPerChapter: 3, arcs: 9, outcomes: 12 } },
  { name: "300 章当量", options: { chapters: 300, eventsPerChapter: 2, arcs: 8, outcomes: 10 } },
  { name: "线多果少", options: { chapters: 20, eventsPerChapter: 3, arcs: 22, outcomes: 2 } },
  { name: "线少果多", options: { chapters: 20, eventsPerChapter: 3, arcs: 2, outcomes: 26 } },
  { name: "双超一屏", options: { chapters: 24, eventsPerChapter: 3, arcs: 16, outcomes: 18 } },
])("$name：全部事件、锚点与结果都完成排布且纵向不溢出", ({ options }) => {
  const started = performance.now();
  const book = buildScaleBook(options);
  const layout = eventTreeLayout(book, FRAME.width, FRAME.height);
  expect(performance.now() - started).toBeLessThan(3000);
  expect(layout.positions.size).toBe(book.events.length);
  expect(layout.arcAnchors.size).toBe(options.arcs);
  expect(layout.outcomeBoxes.size).toBe(options.outcomes);
  for (const position of layout.positions.values()) {
    expect(position.y).toBeGreaterThanOrEqual(layout.outcomeBandBottom + CONTENT_GAP - 0.01);
    expect(position.y + MARKER_RADIUS).toBeLessThanOrEqual(layout.anchorRowY - CONTENT_GAP + 0.01);
  }
  if (options.arcs > 8 || options.outcomes > 10) expect(layout.width).toBeGreaterThan(FRAME.width);
});

it("参考尺寸的120事件保持一屏纵向内容与完整首末文案", () => {
  const book = buildScaleBook({ chapters: 30, eventsPerChapter: 4, arcs: 7, outcomes: 9 });
  const layout = eventTreeLayout(book, 1352, 755);
  expect(layout.width).toBe(1352);
  expect(layout.anchorRowY).toBe(614);
  expect(layout.arcAnchors.get("arc-0")!.x).toBeCloseTo(78.725);
  expect(layout.arcAnchors.get("arc-6")!.x).toBeCloseTo(1273.275);
  expect(layout.positions.get("ev-30-3")!.x).toBeCloseTo(377.3625);
  expect(layout.positions.get("ev-30-3")!.y).toBe(134);
  expect(new Set([...layout.positions.values()].map(position => position.column))).toEqual(new Set([0]));
  for (const box of layout.outcomeBoxes.values()) {
    expect(box.left).toBeGreaterThanOrEqual(16);
    expect(box.left + box.width).toBeLessThanOrEqual(1352 - 16);
  }
  for (const link of book.event_outcome_links) expect(layout.positions.get(link.event_id)!.x).toBe(layout.outcomeBoxes.get(link.outcome_id)!.x);
});

it.each([{ width: 1144, height: 714 }, { width: 984, height: 534 }])("桌面可用高度$height不把120事件强制切出空尾屏", ({ width, height }) => {
  const book = buildScaleBook({ chapters: 30, eventsPerChapter: 4, arcs: 7, outcomes: 9 });
  const layout = eventTreeLayout(book, width, height);
  expect(new Set([...layout.positions.values()].map(position => position.column))).toEqual(new Set([0]));
  expect(layout.positions.size).toBe(120);
  const last = layout.positions.get("ev-30-3")!;
  const linkedOutcome = layout.outcomeBoxes.get("oc-2")!;
  expect(Math.abs(last.x - linkedOutcome.x)).toBeLessThanOrEqual(30);
  expect(layout.anchorRowY + 70).toBeLessThanOrEqual(height);
});

it("多结果事件仍只有一个身份，所有真实结果平等参与几何中点", () => {
  const book = buildScaleBook({ chapters: 1, eventsPerChapter: 1, arcs: 1, outcomes: 2 });
  book.event_outcome_links.push({ event_id: "ev-1-0", outcome_id: "oc-1", reason: "第二真实结果" });
  const layout = eventTreeLayout(book, FRAME.width, FRAME.height);
  expect(layout.positions.size).toBe(1);
  expect(layout.positions.get("ev-1-0")!.x).toBe((layout.outcomeBoxes.get("oc-0")!.x + layout.outcomeBoxes.get("oc-1")!.x) / 2);
});

it("400事件密集关联同一结果时固定点击区域不重叠", () => {
  const book = buildScaleBook({ chapters: 100, eventsPerChapter: 4, arcs: 1, outcomes: 1 });
  const points = [...eventTreeLayout(book, 1352, 755).positions.values()];
  let overlaps = 0;
  for (let index = 0; index < points.length; index++) for (const other of points.slice(index + 1)) {
    if (Math.abs(points[index].x - other.x) < 28 && Math.abs(points[index].y - other.y) < 28) overlaps++;
  }
  expect(overlaps).toBe(0);
});

it("未关联事件完整可见且局部向上阅读，不铺成横纵同步推进的斜坡", () => {
  const book = buildScaleBook({ chapters: 30, eventsPerChapter: 4, arcs: 0, outcomes: 0 });
  book.event_arc_links = [];
  book.event_outcome_links = [];
  const layout = eventTreeLayout(book, 1352, 755);
  const points = book.events.map(event => layout.positions.get(event.event_id)!);
  expect(points).toHaveLength(120);
  expect(layout.arcAnchors.size).toBe(0);
  expect(layout.outcomeBoxes.size).toBe(0);
  expect(points[0].x).toBe(points[1].x);
  expect(points[0].y).toBeGreaterThan(points[1].y);
  let upwardResets = 0;
  for (let index = 1; index < points.length; index++) if (points[index].y > points[index - 1].y) upwardResets++;
  expect(upwardResets).toBeGreaterThan(2);
});

it("完整长标题及说明决定上下文案间距和画布范围", () => {
  const book = buildScaleBook({ chapters: 26, eventsPerChapter: 6, arcs: 8, outcomes: 8 });
  book.arcs = book.arcs.map(arc => ({ ...arc, title: "圣城六年：人质、太学与兵部暗线", objective: "在圣城站住脚，顺着军报与漕运粮道查明布置，并明确六年等待的目标" }));
  book.outcomes = book.outcomes.map(outcome => ({ ...outcome, title: "贺家军以‘演习’逼出人质而不担谋反之名", description: "朝廷仍以人质相制。".repeat(8) }));
  const layout = eventTreeLayout(book, 984, 534);
  expect(layout.width).toBeGreaterThan(984);
  const anchors = [...layout.arcAnchors.values()];
  const outcomes = [...layout.outcomeBoxes.values()];
  for (let index = 1; index < anchors.length; index++) {
    expect(anchors[index].x - anchors[index].width / 2 - (anchors[index - 1].x + anchors[index - 1].width / 2)).toBeGreaterThanOrEqual(CONTENT_GAP);
  }
  for (let index = 1; index < outcomes.length; index++) {
    expect(outcomes[index].left - outcomes[index - 1].left - outcomes[index - 1].width).toBeGreaterThanOrEqual(CONTENT_GAP);
  }
  for (const box of outcomes) expect(box.top + box.height).toBeLessThanOrEqual(layout.outcomeBandBottom);
  for (const point of layout.positions.values()) expect(point.y - MARKER_RADIUS).toBeGreaterThanOrEqual(layout.outcomeBandBottom + CONTENT_GAP);
});

it("文案横向展开且稀疏节点保持紧凑的纵向间距", () => {
  const book = buildScaleBook({ chapters: 3, eventsPerChapter: 3, arcs: 3, outcomes: 3 });
  const layout = eventTreeLayout(book, 2400, 900);
  const anchors = [...layout.arcAnchors.values()];
  const outcomes = [...layout.outcomeBoxes.values()];
  for (let index = 1; index < anchors.length; index++) {
    const gap = anchors[index].x - anchors[index].width / 2 - anchors[index - 1].x - anchors[index - 1].width / 2;
    expect(gap).toBeGreaterThanOrEqual(CONTENT_GAP);
  }
  for (let index = 1; index < outcomes.length; index++) {
    const gap = outcomes[index].left - outcomes[index - 1].left - outcomes[index - 1].width;
    expect(gap).toBeGreaterThanOrEqual(CONTENT_GAP);
  }
  expect(anchors[0].x - anchors[0].width / 2).toBeCloseTo(CONTENT_GAP);
  expect(anchors.at(-1)!.x + anchors.at(-1)!.width / 2).toBeCloseTo(2400 - CONTENT_GAP);
  const local = ["ev-1-0", "ev-2-0", "ev-3-0"].map(id => layout.positions.get(id)!);
  for (let index = 1; index < local.length; index++) {
    expect(local[index - 1].y - local[index].y).toBeGreaterThanOrEqual(28);
    expect(local[index - 1].y - local[index].y).toBeLessThanOrEqual(34);
  }
});
