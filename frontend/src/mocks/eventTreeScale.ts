import { eventQueueFixture, fixtureEventDetail } from "./eventQueueFixture";
import { indexEventQueues } from "../api/eventQueues";
import type { EventTreeEvent, EventTreeListResponse } from "../api/narrativeTypes";

interface ScaleOptions {
  chapters: number;
  eventsPerChapter: number;
  trees: number;
  outcomes: number;
  levels?: number;
}

/** 按夹具包含边读取一棵完整子树，不增加父包含或复制事件 */
export function scaleSubtreeIds(book: EventTreeListResponse, rootId: string): string[] {
  const index = indexEventQueues(book);
  const treeId = index.trees.has(rootId) ? rootId : index.eventTree.get(rootId);
  if (!treeId) return [];
  const seen = new Set<string>();
  const pending = [treeId];
  while (pending.length) { const key = pending.pop()!; if (seen.has(key)) continue; seen.add(key); pending.push(...index.children.get(key)!); }
  return index.order.filter(key => seen.has(key)).flatMap(key => index.trees.get(key)!.event_ids);

}

/** 规模预览的详情与原文从同一包含结构夹具读取 */
export function scaleEventTreeResponse(book: EventTreeListResponse, path: string, params: URLSearchParams, runId = book.run_id): { status: number; data: unknown } {
  if (path.endsWith("/event-trees")) return { status: 200, data: { ...book, run_id: runId } };
  const id = decodeURIComponent(path.split("/").at(path.endsWith("/source") ? -2 : -1)!);
  const event = book.events.find(item => item.event_id === id);
  if (!event) return { status: 404, data: { detail: "NODE_NOT_FOUND" } };
  const chapterId = Number(params.get("chapter_id")) || event.chapter_id;
  if (path.endsWith("/source")) return { status: 200, data: { chapter_id: chapterId, title: book.chapters.find(chapter => chapter.chapter_id === chapterId)!.title, paragraphs: [{ paragraph_id: chapterId, paragraph_index: 0, text: `原文 ${chapterId}：${event.title}。` + "这一段是独立事件树验收夹具的正文。".repeat(40) }], evidence_scope: "paragraph", evidence: [{ chapter_id: chapterId, paragraph_id: chapterId }] } };
  return { status: 200, data: fixtureEventDetail(book, id, runId) };
}

/** 结构化规模夹具提供真实根事件和包含边，不代表真实长篇业务验收 */
export function buildScaleBook({ chapters, eventsPerChapter, trees, outcomes, levels = 4 }: ScaleOptions): EventTreeListResponse {
  if (!Number.isInteger(levels) || levels < 1) throw new Error("夹具层数必须是正整数");
  const chapterList = Array.from({ length: chapters }, (_, index) => ({ chapter_id: index + 1, title: `第 ${index + 1} 章`, chapter_order: index + 1 }));
  const children: EventTreeEvent[] = [];
  let position = 0;
  for (let chapter = 1; chapter <= chapters; chapter++) {
    for (let index = 0; index < eventsPerChapter; index++) {
      position += 100;
      children.push({
        event_id: `ev-${chapter}-${index}`, is_event_line: false, from: chapter, to: chapter,
        title: `第 ${chapter} 章事件 ${index}`, problem: `待解决的问题 ${chapter}-${index}`,
        summary: `概要 ${chapter}-${index}`, event_type: "推进", status: "进行中",
        first_text_position: position, chapter_id: chapter, chapter_order: chapter,
      });
    }
  }
  const roots: EventTreeEvent[] = Array.from({ length: trees }, (_, index) => ({
    event_id: `root-${index}`, is_event_line: true, from: 1, to: chapters, title: `事件树 ${index}`, problem: `事件树 ${index} 的核心问题`, summary: `事件树 ${index} 的概要`,
    event_type: "调查", status: "进行中", first_text_position: (index + 1) * 100, chapter_id: 1, chapter_order: 1,
  }));
  const membersByRoot = roots.map((_, rootIndex) => children.filter((__, index) => index % roots.length === rootIndex));
  const branchWidths = membersByRoot.map(members => Math.max(1, Math.ceil(members.length / levels)));
  const edges = membersByRoot.flatMap((members, rootIndex) => members.map((event, index) => ({
    parent: index < branchWidths[rootIndex] ? roots[rootIndex].event_id : members[index - branchWidths[rootIndex]].event_id,
    child: event.event_id, reason: "子事件是上层事件的一部分", evidence: [{ chapter_id: event.chapter_id }],
  })));
  const events = [...roots, ...children];
  const outcomeList = Array.from({ length: outcomes }, (_, index) => ({ outcome_id: `oc-${index}`, title: `结果 ${index}`, description: `结果 ${index} 的说明文字`, first_text_position: (index + 1) * 500 }));
  return eventQueueFixture({ run_id: "run-scale", chapters: chapterList, events, edges,
    outcomes: outcomeList, relations: [], foreshadowing_actions: [] });
}
