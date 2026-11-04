import { describe, expect, it } from "vitest";
import { selectedEventLineFixture } from "@/mocks/eventQueueFixture";
import { indexEventQueues } from "./eventQueues";

describe("indexEventQueues", () => {
  it("事件线入口是独立树身份，成员从本树首成员开始", () => {
    const book = selectedEventLineFixture();
    const index = indexEventQueues(book);
    expect(index.eventTree.get("a1")).toBe("tree-of-a0");
    expect(index.treeEvents("tree-of-a0")).toEqual(["a0", "a1", "a2", "s0", "s1"]);
    expect(index.treeEvents("tree-of-b0")).toEqual(["b0", "b1", "s0", "s1"]);
  });

  it("低覆盖正式响应照常读取，未覆盖事件仍保留在真实事件索引", () => {
    const book = selectedEventLineFixture();
    const index = indexEventQueues(book);
    const covered = new Set(book.event_line_ids.flatMap(index.treeEvents));
    expect(covered.size).toBe(10);
    expect(book.events).toHaveLength(20);
    expect(book.counts.all_events).toBe(20);
    expect(index.eventTree.has("uncovered-9")).toBe(true);
    expect(book.events.find(event => event.event_id === "uncovered-9")).toBeDefined();
  });

  it("前端不重复裁定后端已经返回的事件线数量", () => {
    const book = selectedEventLineFixture();
    book.event_line_ids = ["tree-of-a0"];
    book.queues = book.queues.map(tree => ({ ...tree, is_event_line: tree.tree_id === "tree-of-a0" }));
    book.events = book.events.map(event => ({ ...event, is_event_line: event.event_id === "a0" }));
    book.counts.event_lines = 1;
    expect(() => indexEventQueues(book)).not.toThrow();
  });

  it("完整性校验仍拒绝未登记到队列的真实事件", () => {
    const book = selectedEventLineFixture();
    book.queues = book.queues.filter(tree => !tree.event_ids.includes("uncovered-9"));
    expect(() => indexEventQueues(book)).toThrow("响应不完整");
  });
});
