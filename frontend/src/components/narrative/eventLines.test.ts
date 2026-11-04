import { describe, expect, it } from "vitest";
import { buildEventLines } from "./eventLines";
import { referenceBook } from "@/mocks/eventTreeReference";
import { buildScaleBook } from "@/mocks/eventTreeScale";
import { tree } from "@/mocks/narrativeData";
import { selectedEventLineFixture } from "@/mocks/eventQueueFixture";

describe("buildEventLines", () => {
  it("直接采用正式事件线身份，不按主题重新分组", () => {
    const result = buildEventLines(referenceBook);
    expect(result.lines.map(line => line.id)).toEqual(referenceBook.event_line_ids);
    expect(result.lineByEvent.size).toBe(referenceBook.events.length);
    expect(result.lines.reduce((total, line) => total + line.eventCount, 0)).toBeGreaterThan(referenceBook.events.length);
  });
  it("待诊断的十二个入口原样保留", () => {
    const book = buildScaleBook({ chapters: 30, eventsPerChapter: 4, trees: 12, outcomes: 2 });
    expect(buildEventLines(book).lines.map(line => line.id)).toEqual(book.event_line_ids);
    expect(buildEventLines(book).lines).toHaveLength(12);
  });
  it("队内顺序不被章节位置覆盖", () => {
    const book = structuredClone(tree);
    book.queues[0].event_ids.reverse();
    const queue = book.queues[0];
    const oldId = queue.tree_id;
    queue.tree_id = "tree-renamed";
    book.queue_references = book.queue_references.map(edge => ({
      ...edge,
      parent_tree_id: edge.parent_tree_id === oldId ? queue.tree_id : edge.parent_tree_id,
      child_tree_id: edge.child_tree_id === oldId ? queue.tree_id : edge.child_tree_id,
    }));
    book.event_line_ids = book.event_line_ids.map(id => id === oldId ? queue.tree_id : id);
    const line = buildEventLines(book).lines.find(item => item.id === queue.tree_id)!;
    expect(line.eventIds).toEqual(queue.event_ids);
  });
  it("共享事件映射到全部可达事件线，业务事件只保存一份", () => {
    const result = buildEventLines(referenceBook);
    const shared = [...result.lineByEvent.values()].filter(lines => lines.length > 1);
    expect(shared.length).toBeGreaterThan(0);
    expect(new Set(referenceBook.events.map(event => event.event_id)).size).toBe(referenceBook.events.length);
  });
  it("任意标记入口按完整可达子结构展示，共享事件在每条线内只出现一次", () => {
    const book = selectedEventLineFixture();
    const result = buildEventLines(book);
    expect(result.lines.map(line => line.id)).toEqual(["tree-of-a0", "tree-of-b0", "tree-of-c", "tree-of-d", "tree-of-e"]);
    expect(result.lines.find(line => line.id === "tree-of-a0")!.eventIds).toEqual(["a0", "a1", "a2", "s0", "s1"]);
    expect(result.lines.find(line => line.id === "tree-of-b0")!.eventIds).toEqual(["b0", "b1", "s0", "s1"]);
    expect(result.lineByEvent.get("s1")!.map(line => line.id)).toEqual(["tree-of-a0", "tree-of-b0"]);
    expect(result.lines.every(line => new Set(line.eventIds).size === line.eventCount)).toBe(true);
    expect(result.lines.reduce((total, line) => total + line.eventCount, 0)).toBe(12);
    expect(new Set(result.lines.flatMap(line => line.eventIds)).size).toBe(10);
    expect(book.events).toHaveLength(20);
  });
  it("深链提升节点不改变整条线的成员顺序", () => {
    const before = buildEventLines(referenceBook);
    const target = referenceBook.events.find(event => !before.lineByEvent.get(event.event_id)![0].nodes.some(node => node.eventId === event.event_id))!;
    const after = buildEventLines(referenceBook, target.event_id);
    for (const line of after.lineByEvent.get(target.event_id)!) {
      expect(line.nodes.some(node => node.eventId === target.event_id)).toBe(true);
      expect(line.eventIds).toEqual(before.lines.find(item => item.id === line.id)!.eventIds);
    }
  });
});
