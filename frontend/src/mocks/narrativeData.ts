import { eventQueueFixture, fixtureEventDetail } from "./eventQueueFixture";
import type { EventCardDetail, EventTreeEvent, EventTreeListResponse, PlotlineChange, PlotlineTimelineResponse } from "../api/narrativeTypes";

export const chapters = [1, 2, 3].map(id => ({ chapter_id: id, order: id, title: `章节 ${id}` }));
export const changes: PlotlineChange[] = [1, 2, 3].map(chapter => ({
  plotline_change_id: `change-${chapter}`, dimension: "plot", subject_id: "letter", subject_title: "旧信之谜",
  chapter_id: chapter, chapter_order: chapter, title: `信件线索 ${chapter}`, before: "未知", after: `线索 ${chapter}`,
  deltas: [], action: null, evidence_scope: "paragraph", anchor_paragraph_ids: [chapter],
  evidence: [{ chapter_id: chapter, paragraph_id: chapter }], source_event_ids: [], source_fact_ids: [`fact-${chapter}`],
}));
export const eventA: EventTreeEvent = { event_id: "event:a", is_event_line: false, from: 1, to: 3, title: "最初的信", problem: "确认信件来自何处", summary: "调查者找到最初的信，并着手确认信件来源。", event_type: "调查", status: "ongoing", first_text_position: 1, chapter_id: 1, chapter_order: 1 };
export const eventB: EventTreeEvent = { ...eventA, event_id: "event:b", title: "隐藏的末页事件", first_text_position: 3, chapter_id: 3, chapter_order: 3 };
export const childEvent = { ...eventA, event_id: "child:a", title: "辨认信封印记" };
export const grandchildEvent = { ...eventA, event_id: "grandchild:a", title: "核对邮戳" };
export const tree: EventTreeListResponse = eventQueueFixture({
  run_id: "run-a", chapters: chapters.map(chapter => ({ ...chapter, chapter_order: chapter.order })),
  events: [eventA, childEvent, grandchildEvent, eventB], outcomes: [{ outcome_id: "outcome:a", title: "旧信来源查明", description: "两个事件共同确认信件来自旧港口", first_text_position: 3 }],
  edges: [{ parent: eventA.event_id, child: childEvent.event_id, reason: "辨认印记是查明信件来源的一部分", evidence: [{ chapter_id: 1, paragraph_id: 1 }] }, { parent: childEvent.event_id, child: grandchildEvent.event_id, reason: "核对邮戳是辨认信封印记的一部分", evidence: [{ chapter_id: 1, paragraph_id: 1 }] }],
  relations: [{ source_kind: "event", source_id: eventA.event_id, target_kind: "event", target_id: childEvent.event_id, relation_type: "influence", reason: "发现信件促使调查印记", locator: { target_kind: "event", target_id: childEvent.event_id, tree_id: "tree-of-event:a", tree_position: 0, event_line_ids: ["tree-of-event:a"], evidence_position: 1, title: childEvent.title } }],
  foreshadowing_actions: [],
});
export function timeline(cutoff = 1): PlotlineTimelineResponse {
  const visible = changes.filter(change => change.chapter_order <= cutoff);
  return {
    run_id: "run-a", chapters, through_chapter_id: cutoff, changes: visible,
    states: [{ subject_id: "letter", subject_title: "旧信之谜", dimension: "plot", state: `线索 ${cutoff}`, chapter_id: cutoff, chapter_order: cutoff }],
    state_counts: { plot: 1 }, state_total: 1,
    total: visible.length, next_cursor: null,
    distribution: visible.map(change => ({ chapter_id: change.chapter_id, chapter_order: change.chapter_order, dimension: change.dimension, count: 1 })),
  };
}
export function treeDetail(event: EventTreeEvent): EventCardDetail {
  return { ...fixtureEventDetail(tree, event.event_id), progress: "investigating",
    characters: [{ name: "林舟", entity_id: "lin" }] };

}

/** 正式契约测试数据，不读取或转换任何业务库旧记录 */
export function eventTreeResponse(path: string, params: URLSearchParams, runId = "run-a"): { status: number; data: unknown } {
  const id = decodeURIComponent(path.split("/").at(path.endsWith("/source") ? -2 : -1)!);
  const event = [eventA, eventB, childEvent, grandchildEvent].find(item => item.event_id === id);
  if (path.endsWith("/source")) {
    const chapter = Number(params.get("chapter_id")) || event?.chapter_id || 1;
    return { status: 200, data: { chapter_id: chapter, title: `章节 ${chapter}`, paragraphs: [{ paragraph_id: chapter, paragraph_index: 0, text: `原文 ${chapter} ` + "正文".repeat(800) }], evidence_scope: "paragraph", evidence: [{ chapter_id: chapter, paragraph_id: chapter }] } };
  }
  if (path.includes("/nodes/")) return event ? { status: 200, data: { ...treeDetail(event), run_id: runId } } : { status: 404, data: { detail: "NODE_NOT_FOUND" } };
  return { status: 200, data: { ...tree, run_id: runId } };
}

/** 开发预览与浏览器验收使用同一份独立查询夹具，不连接业务库 */
export function narrativeResponse(path: string, params: URLSearchParams, runId = "run-a"): { status: number; data: unknown } {
  const cutoff = Number(params.get("through_chapter_id")) || 1;
  if (path.includes("/event-trees")) return eventTreeResponse(path, params, runId);
  const id = decodeURIComponent(path.split("/").at(path.endsWith("/source") ? -2 : -1)!);
  const change = changes.find(item => item.plotline_change_id === id);

  if (path.includes("/timeline/changes/") && (!change || change.chapter_order > cutoff)) return { status: 404, data: { detail: { code: "CHANGE_NOT_VISIBLE" } } };
  if (path.endsWith("/source")) {
    const chapter = Number(params.get("chapter_id")) || change?.chapter_id || 1;
    return { status: 200, data: { chapter_id: chapter, title: `章节 ${chapter}`, paragraphs: [{ paragraph_id: chapter, paragraph_index: 0, text: `原文 ${chapter} ` + "正文".repeat(800) }] } };
  }
  if (path.includes("/timeline/changes/")) return { status: 200, data: change };
  if (path.endsWith("/timeline/states")) {
    const data = timeline(cutoff);
    const dimension = params.get("dimension"), subject = params.get("subject_id");
    const matched = data.states.filter(state => (!dimension || state.dimension === dimension) && (!subject || state.subject_id === subject));
    const offset = Number(params.get("cursor")) || 0, limit = Number(params.get("limit")) || 100;
    if (params.get("summary") === "true") return { status: 200, data: { ...data, states: matched, state_total: matched.length } };
    return { status: 200, data: { states: matched.slice(offset, offset + limit), total: matched.length, next_cursor: offset + limit < matched.length ? String(offset + limit) : null } };
  }
  if (path.endsWith("/timeline/subjects")) {
    const subject = params.get("subject_id"), q = params.get("q");
    const matched = timeline(cutoff).states.filter(state => (!q || state.subject_title.includes(q)) && (!subject || state.subject_id === subject));
    return { status: 200, data: { subjects: matched.map(state => ({ subject_id: state.subject_id, subject_title: state.subject_title, dimension: state.dimension })), total: matched.length, next_cursor: null } };
  }
  if (path.endsWith("/timeline")) {
    const data = timeline(cutoff);
    data.run_id = runId;
    if (params.get("meta_only") === "true") return { status: 200, data: { ...data, changes: [], states: [], state_counts: {}, state_total: 0, total: 0, distribution: [] } };
    const source = params.get("source_fact_id"), subject = params.get("subject_id"), dimension = params.get("dimension"), q = params.get("q");
    data.changes = data.changes.filter(item => (!source || item.source_fact_ids.includes(source)) && (!subject || item.subject_id === subject) && (!dimension || item.dimension === dimension) && (!q || item.title.includes(q)));
    data.distribution = data.changes.map(item => ({ chapter_id: item.chapter_id, chapter_order: item.chapter_order, dimension: item.dimension, count: 1 }));
    data.changes = data.changes.filter(item => item.chapter_id >= (Number(params.get("window_start_chapter_id")) || 1));
    data.total = data.changes.length;
    return { status: 200, data };
  }
  return { status: 404, data: { detail: "NOT_FOUND" } };
}
