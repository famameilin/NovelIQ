import type { EventCardDetail, EventTreeEvent, EventTreeListResponse, PlotlineChange, PlotlineTimelineResponse } from "../api/narrativeTypes";

export const chapters = [1, 2, 3].map(id => ({ chapter_id: id, order: id, title: `章节 ${id}` }));
export const changes: PlotlineChange[] = [1, 2, 3].map(chapter => ({
  plotline_change_id: `change-${chapter}`, dimension: "plot", subject_id: "letter", subject_title: "旧信之谜",
  chapter_id: chapter, chapter_order: chapter, title: `信件线索 ${chapter}`, before: "未知", after: `线索 ${chapter}`,
  deltas: [], action: null, evidence_scope: "paragraph", anchor_paragraph_ids: [chapter],
  evidence: [{ chapter_id: chapter, paragraph_id: chapter }], source_event_ids: [], source_fact_ids: [`fact-${chapter}`],
}));
export const arc = { arc_id: "a", parent_arc_id: null, kind: "main", title: "调查旧信", objective: "解开谜团" };
export const eventA: EventTreeEvent = { event_id: "event:a", title: "最初的信", summary: "调查者找到最初的信，并着手确认信件来源。", event_type: "调查", status: "ongoing", first_text_position: 1, chapter_id: 1, chapter_order: 1 };
export const eventB: EventTreeEvent = { ...eventA, event_id: "event:b", title: "隐藏的末页事件", first_text_position: 3, chapter_id: 3, chapter_order: 3 };
export const childEvent = { ...eventA, event_id: "child:a", title: "辨认信封印记" };
export const grandchildEvent = { ...eventA, event_id: "grandchild:a", title: "核对邮戳" };
export const tree: EventTreeListResponse = {
  run_id: "run-a", chapters: chapters.map(chapter => ({ ...chapter, chapter_order: chapter.order })),
  counts: { top_level_events: 2, child_events: 2, all_events: 4, declarations: 2, outcomes: 1, event_outcome_links: 2, arcs: 1, event_arc_links: 2, relations: 1, foreshadowing_actions: 0 },
  arcs: [arc], events: [eventA, eventB], outcomes: [{ outcome_id: "outcome:a", title: "旧信来源查明", description: "两个事件共同确认信件来自旧港口", first_text_position: 3 }],
  event_arc_links: [eventA, eventB].map(event => ({ event_id: event.event_id, arc_id: "a", role: "推进调查", reason: "原文行动推进谜题" })),
  event_outcome_links: [eventA, eventB].map(event => ({ event_id: event.event_id, outcome_id: "outcome:a", reason: "信件来源得到确认" })),
  relations: [{ source_kind: "event", source_id: eventA.event_id, target_kind: "event", target_id: childEvent.event_id, relation_type: "influence", reason: "发现信件促使调查印记", locator: { target_kind: "event", target_id: childEvent.event_id, top_level_event_id: eventA.event_id, ancestor_event_ids: [eventA.event_id], evidence_position: 1, title: childEvent.title } }],
  foreshadowing_actions: [], next_cursor: null,
};
export function timeline(cutoff = 1): PlotlineTimelineResponse {
  const visible = changes.filter(change => change.chapter_order <= cutoff);
  return {
    run_id: "run-a", chapters, through_chapter_id: cutoff, changes: visible,
    states: [{ subject_id: "letter", subject_title: "旧信之谜", dimension: "plot", state: `线索 ${cutoff}`, chapter_id: cutoff, chapter_order: cutoff }],
    subjects: [{ subject_id: "letter", subject_title: "旧信之谜", dimension: "plot" }],
    total: visible.length, next_cursor: null,
    distribution: visible.map(change => ({ chapter_id: change.chapter_id, chapter_order: change.chapter_order, dimension: change.dimension, count: 1 })),
  };
}
export function treeDetail(event: EventTreeEvent): EventCardDetail {
  const ancestry = event.event_id === childEvent.event_id ? [eventA.event_id] : event.event_id === grandchildEvent.event_id ? [eventA.event_id, childEvent.event_id] : [];
  const children = event.event_id === eventA.event_id ? [childEvent] : event.event_id === childEvent.event_id ? [grandchildEvent] : [];
  return { kind: "event", event_id: event.event_id, run_id: "run-a", title: event.title, summary: event.summary, progress: "investigating", event_type: event.event_type, status: event.status,
    arcs: [{ ...arc, role: "推进调查", reason: "原文行动推进谜题" }], characters: [{ name: "林舟", entity_id: "lin" }],
    direct_children: children.map(child => ({ event_id: child.event_id, title: child.title, event_type: child.event_type, status: child.status })),
    evidence_scope: "paragraph", evidence: [{ chapter_id: event.chapter_id, paragraph_id: event.chapter_id }], source_chapters: [event.chapter_id], ancestry, relations: tree.relations.filter(relation => relation.source_id === event.event_id),
  };
}

/** 正式契约测试数据，不读取或转换任何业务库旧记录 */
export function eventTreeResponse(path: string, params: URLSearchParams, runId = "run-a"): { status: number; data: unknown } {
  const id = decodeURIComponent(path.split("/").at(path.endsWith("/source") ? -2 : -1)!);
  const event = [eventA, eventB, childEvent, grandchildEvent].find(item => item.event_id === id);
  if (path.endsWith("/source")) {
    const chapter = Number(params.get("chapter_id")) || event?.chapter_id || 1;
    return { status: 200, data: { chapter_id: chapter, title: `章节 ${chapter}`, paragraphs: [{ paragraph_id: chapter, paragraph_index: 0, text: `原文 ${chapter} ` + "正文".repeat(800) }], ...(params.get("kind") === "declaration" ? { locator: { target_kind: "declaration", target_id: id, top_level_event_id: null, ancestor_event_ids: [], evidence_position: 1, title: "比对印记" }, evidence_scope: "paragraph", evidence: [{ chapter_id: 1, paragraph_id: 1 }] } : {}) } };
  }
  if (path.includes("/nodes/")) return event ? { status: 200, data: { ...treeDetail(event), run_id: runId } } : { status: 404, data: { detail: "NODE_NOT_FOUND" } };
  const offset = params.get("cursor") ? 1 : 0;
  return { status: 200, data: { ...tree, run_id: runId, events: [tree.events[offset]], next_cursor: offset ? null : "second" } };
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
  if (path.endsWith("/timeline")) {
    const data = timeline(cutoff);
    const source = params.get("source_fact_id"), subject = params.get("subject_id"), dimension = params.get("dimension"), q = params.get("q");
    data.run_id = runId;
    data.changes = data.changes.filter(item => (!source || item.source_fact_ids.includes(source)) && (!subject || item.subject_id === subject) && (!dimension || item.dimension === dimension) && (!q || item.title.includes(q)));
    data.distribution = data.changes.map(item => ({ chapter_id: item.chapter_id, chapter_order: item.chapter_order, dimension: item.dimension, count: 1 }));
    data.changes = data.changes.filter(item => item.chapter_id >= (Number(params.get("window_start_chapter_id")) || 1));
    data.total = data.changes.length;
    return { status: 200, data };
  }
  return { status: 404, data: { detail: "NOT_FOUND" } };
}
