import { eventDisplayKey } from "@/api/eventQueues";
import { describe, expect, it } from "vitest";
import { buildEventLines } from "./eventLines";
import { eventLineLayout, EVENT_LINE_MIN_WIDTH, NODE_GAP, RAIL_WIDTH, ROW_PITCH_MIN, ROW_TOP } from "./eventLineLayout";
import { referenceBook } from "@/mocks/eventTreeReference";
import { eventQueueFixture } from "@/mocks/eventQueueFixture";

function layoutFixture(width = 1200, height = 800) {
  return eventLineLayout(buildEventLines(referenceBook), width, height);
}

describe("eventLineLayout", () => {
  it("事件树节点按本身份顺序等距排开，并携带所属事件数", () => {
    const layout = layoutFixture();
    const placed = layout.lines[0];
    expect(placed.nodes.length).toBeGreaterThan(1);
    expect(placed.nodes[0].x).toBe(layout.trackStart);
    const gaps = placed.nodes.slice(1).map((node, index) => node.x - placed.nodes[index].x);
    expect(new Set(gaps)).toEqual(new Set([NODE_GAP]));
    for (const node of placed.nodes) {
      expect(node.node.eventIds.length).toBeGreaterThan(0);
      expect(node.node.eventIds).toContain(node.node.eventId);
    }
    expect(placed.end.x).toBeGreaterThanOrEqual(placed.nodes.at(-1)!.x);
    expect(placed.path.endsWith(`${placed.end.x} ${placed.end.y}`)).toBe(true);
  });

  it("全部叙事线按同一行距铺满画布高度，导轨固定宽度", () => {
    const layout = layoutFixture(1200, 600);
    expect(layout.lines).toHaveLength(7);
    expect(layout.width).toBeGreaterThanOrEqual(Math.max(EVENT_LINE_MIN_WIDTH, 1200));
    expect(layout.height).toBe(600);
    expect(layout.rowPitch).toBeGreaterThan(ROW_PITCH_MIN);
    expect(layout.rail.width).toBe(RAIL_WIDTH);
    for (let index = 1; index < layout.lines.length; index++) {
      expect(layout.lines[index].y - layout.lines[index - 1].y).toBeCloseTo(layout.rowPitch, 6);
    }
    expect(layout.lines[0].y - layout.rowPitch / 2).toBeGreaterThanOrEqual(ROW_TOP);
    expect(layout.height - (layout.lines.at(-1)!.y + layout.rowPitch / 2)).toBeLessThanOrEqual(32.5);
  });

  it("关键节点落在线身且按所属事件数量缩放", () => {
    const layout = layoutFixture();
    const counts = layout.lines.map(placed => placed.nodes.length);
    expect(Math.min(...counts)).toBeGreaterThan(1);
    expect(Math.max(...counts)).toBeGreaterThan(5);
    for (const placed of layout.lines) {
      const xs = placed.nodes.map(node => node.x);
      expect(xs).toEqual([...xs].sort((a, b) => a - b));
      for (const node of placed.nodes) {
        expect(node.y).toBeCloseTo(placed.y, 6);
        expect(node.size).toBeGreaterThanOrEqual(8);
        expect(node.size).toBeLessThanOrEqual(14);
        expect(node.labelY).toBeCloseTo(node.y - (node.size / 2 + 5), 6);
        expect(layout.nodeByEvent.get(eventDisplayKey(placed.line.id, node.node.eventId))).toBe(node);
        expect(layout.pointByEvent.get(eventDisplayKey(placed.line.id, node.node.eventId)))
          .toEqual({ x: node.x, y: node.y, lineId: placed.line.id });
      }
      const ordered = [...placed.nodes].sort((a, b) => b.node.eventIds.length - a.node.eventIds.length);
      expect(ordered[0].size).toBeGreaterThanOrEqual(ordered.at(-1)!.size);
    }
  });

  it("根节点标签让位给导轨，其余关键节点标签互不重叠", () => {
    const layout = layoutFixture();
    for (const placed of layout.lines) {
      if (placed.nodes.some(node => !node.node.isRoot)) {
        expect(placed.nodes.filter(node => node.node.isRoot).every(node => !node.labelVisible)).toBe(true);
      }
      expect(placed.nodes.filter(node => !node.node.isRoot).every(node => node.labelVisible)).toBe(true);
    }
  });

  it("画布宽度按节点最多的叙事线扩展，末端落在画布内", () => {
    const layout = layoutFixture(600, 480);
    expect(layout.width).toBeGreaterThan(600);
    expect(layout.lines.every(placed => placed.end.x < layout.width)).toBe(true);
    const maxNodes = Math.max(...layout.lines.map(placed => placed.nodes.length));
    expect(layout.width).toBeGreaterThanOrEqual(layout.trackStart + (maxNodes - 1) * NODE_GAP);
  });

  it("百个成员的单队列只保留首尾两个关键节点", () => {
    const template = referenceBook.events[0];
    const events = Array.from({ length: 100 }, (_, index) => ({ ...template, event_id: `Q${index}`, title: `事件${index}`, is_event_line: index === 0 }));
    const book = eventQueueFixture({ ...referenceBook, events, event_line_ids: ["Q0"],
      edges: events.slice(1).map((event, index) => ({ parent: events[index].event_id, child: event.event_id,
        reason: "真实父子", evidence: [{ chapter_id: template.chapter_id }] })),
      outcomes: [], relations: [], foreshadowing_actions: [],
    });
    const placed = eventLineLayout(buildEventLines(book), 1200, 800).lines[0];
    expect(placed.nodes).toHaveLength(2);
    expect(placed.nodes[0].node.eventId).toBe("Q0");
    expect(placed.nodes.at(-1)!.node.eventId).toBe("Q99");
    expect(placed.nodes[0].node.eventIds).toHaveLength(99);
    expect(placed.nodes.at(-1)!.node.eventIds).toEqual(["Q99"]);
  });
});
