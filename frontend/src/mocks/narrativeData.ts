import type { NarrativeTreeDetail, NarrativeTreeNode, NarrativeTreeResponse, ProgressionChange, ProgressionTimelineResponse } from "../api/narrativeTypes";

export const chapters = [1, 2, 3].map(id => ({ chapter_id: id, order: id, title: `章节 ${id}` }));
export const changes: ProgressionChange[] = [1, 2, 3].map(chapter => ({
  progression_change_id: `change-${chapter}`, dimension: "plot", subject_id: "letter", subject_title: "旧信之谜",
  chapter_id: chapter, chapter_order: chapter, title: `信件线索 ${chapter}`, before: "未知", after: `线索 ${chapter}`,
  deltas: [], action: null, evidence_scope: "paragraph", anchor_paragraph_ids: [chapter],
  evidence: [{ chapter_id: chapter, paragraph_id: chapter }], source_event_ids: [], source_fact_ids: [`fact-${chapter}`],
}));
export const root: NarrativeTreeNode = { node_id: "root", kind: "root", title: "全书问题", parent_id: null, child_count: 1 };
export const arc: NarrativeTreeNode = { node_id: "arc:a", kind: "arc", title: "调查旧信", parent_id: "root", arc_id: "a", child_count: 2 };
export const eventA: NarrativeTreeNode = { node_id: "event:a", kind: "event", title: "最初的信", parent_id: "arc:a", arc_id: "a", chapter_id: 1, chapter_order: 1, child_count: 0 };
export const eventB: NarrativeTreeNode = { ...eventA, node_id: "event:b", title: "隐藏的末页事件", chapter_id: 3, chapter_order: 3 };
export const tree: NarrativeTreeResponse = {
  run_id: "run-a", title: root.title, chapters, total_events: 2,
  arcs: [{ arc_id: "a", parent_arc_id: null, kind: "main", title: arc.title, objective: "解开谜团", role: "核心冲突", reason: "调查贯穿正文", evidence: [{ event_id: "a" }] }],
  nodes: [root, arc], edges: [{ source_id: "root", target_id: "arc:a", kind: "organization" }], total: 2, next_cursor: null, matches: [],
};
export function timeline(cutoff = 1): ProgressionTimelineResponse {
  const visible = changes.filter(change => change.chapter_order <= cutoff);
  return {
    run_id: "run-a", chapters, through_chapter_id: cutoff, changes: visible,
    states: [{ subject_id: "letter", subject_title: "旧信之谜", dimension: "plot", state: `线索 ${cutoff}`, chapter_id: cutoff, chapter_order: cutoff }],
    subjects: [{ subject_id: "letter", subject_title: "旧信之谜", dimension: "plot" }],
    total: visible.length, next_cursor: null,
    distribution: visible.map(change => ({ chapter_id: change.chapter_id, chapter_order: change.chapter_order, dimension: change.dimension, count: 1 })),
  };
}
export function treeDetail(node: NarrativeTreeNode): NarrativeTreeDetail {
  return { ...node, path: node.node_id === "root" ? [root] : node.kind === "arc" ? [root, arc] : [root, arc, node],
    role: "推动调查", reason: "原文行动推进谜题", evidence_scope: "paragraph", anchor_paragraph_ids: [node.chapter_id ?? 1],
    evidence: [{ chapter_id: node.chapter_id ?? 1, paragraph_id: node.chapter_id ?? 1 }], participants: [], relations: [], references: [],
  };
}

/** 开发预览与浏览器验收使用同一份独立查询夹具，不连接业务库 */
export function narrativeResponse(path: string, params: URLSearchParams, runId = "run-a"): { status: number; data: unknown } {
  const cutoff = Number(params.get("through_chapter_id")) || 1;
  const allNodes = [root, arc, eventA, eventB];
  const id = decodeURIComponent(path.split("/").at(path.endsWith("/source") ? -2 : -1)!);
  const change = changes.find(item => item.progression_change_id === id);
  const node = allNodes.find(item => item.node_id === id);
  if (path.includes("/timeline/changes/") && (!change || change.chapter_order > cutoff)) return { status: 404, data: { detail: { code: "CHANGE_NOT_VISIBLE" } } };
  if (path.endsWith("/source")) {
    const chapter = Number(params.get("chapter_id")) || change?.chapter_id || node?.chapter_id || 1;
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
  if (path.includes("/event-trees/nodes/")) return node ? { status: 200, data: treeDetail(node) } : { status: 404, data: { detail: "NODE_NOT_FOUND" } };
  const data = { ...tree, run_id: runId };
  if (params.get("q") || params.get("chapter_id")) {
    const found = allNodes.filter(item => item.kind === "event" && (!params.get("q") || item.title.includes(params.get("q")!)) && (!params.get("chapter_id") || item.chapter_id === Number(params.get("chapter_id"))));
    return { status: 200, data: { ...data, nodes: allNodes, total: found.length, matches: found.map(item => ({ node_id: item.node_id, title: item.title, ancestor_ids: treeDetail(item).path.slice(0, -1).map(parent => parent.node_id), chapter_id: item.chapter_id ?? null, chapter_order: item.chapter_order ?? null })) } };
  }
  if (params.get("parent_id")) {
    const children = allNodes.filter(item => item.parent_id === params.get("parent_id"));
    const offset = params.get("cursor") ? 1 : 0;
    const pageNodes = children.slice(offset, offset + 1);
    return { status: 200, data: { ...data, nodes: [root, arc, ...pageNodes], edges: [...data.edges, ...pageNodes.map(item => ({ source_id: item.parent_id!, target_id: item.node_id, kind: "organization" }))], total: children.length, next_cursor: children.length > offset + 1 ? "second" : null } };
  }
  if (params.get("expand_all") === "true") return { status: 200, data: { ...data, nodes: allNodes, edges: [...data.edges, ...allNodes.filter(item => item.kind === "event").map(item => ({ source_id: item.parent_id!, target_id: item.node_id, kind: "organization" }))], total: allNodes.length } };
  return { status: 200, data };
}

