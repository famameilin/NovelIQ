import type { EventCardDetail, EventTreeListResponse } from "../api/narrativeTypes";
import { indexEventQueues } from "../api/eventQueues";

export interface FixtureEdge { parent: string; child: string; reason: string; evidence: Array<Record<string, unknown>> }
export type FixtureInput = Pick<EventTreeListResponse, "run_id" | "chapters" | "events" | "outcomes" | "relations" | "foreshadowing_actions"> & {
  edges: FixtureEdge[];
  event_line_ids?: string[];
  organization_status?: EventTreeListResponse["organization_status"];
};

/** 按夹具声明的完整父子图生成不交叠的线性事件树，树身份独立于事件身份 */
export function eventQueueFixture(input: FixtureInput): EventTreeListResponse {
  const parents = new Map(input.events.map(event => [event.event_id, [] as string[]]));
  const children = new Map(input.events.map(event => [event.event_id, [] as string[]]));
  for (const edge of input.edges) {
    parents.get(edge.child)!.push(edge.parent);
    children.get(edge.parent)!.push(edge.child);
  }
  const queues: EventTreeListResponse["queues"] = [];
  const owner = new Map<string, string>();
  const titles = new Map(input.events.map(event => [event.event_id, event]));
  for (const event of input.events) {
    const incoming = parents.get(event.event_id)!;
    if (incoming.length === 1 && children.get(incoming[0])!.length === 1) continue;
    const eventIds = [event.event_id];
    while (children.get(eventIds.at(-1)!)!.length === 1) {
      const next = children.get(eventIds.at(-1)!)![0];
      if (parents.get(next)!.length !== 1) break;
      eventIds.push(next);
    }
    const treeId = `tree-of-${event.event_id}`;
    queues.push({
      tree_id: treeId,
      title: titles.get(event.event_id)?.title ?? event.event_id,
      description: titles.get(event.event_id)?.summary ?? event.event_id,
      is_event_line: false,
      event_ids: eventIds,
    });
    for (const id of eventIds) owner.set(id, treeId);
  }
  const references = input.edges.filter(edge => owner.get(edge.parent) !== owner.get(edge.child)).map(edge => ({
    parent_tree_id: owner.get(edge.parent)!, child_tree_id: owner.get(edge.child)!, reason: edge.reason, evidence: edge.evidence,
  }));
  const targets = new Set(references.map(edge => edge.child_tree_id));
  const roots = queues.filter(tree => !targets.has(tree.tree_id)).map(tree => tree.tree_id);
  const { edges: _, event_line_ids: entries, organization_status: status, ...facts } = input;
  const marked = facts.events.filter(event => event.is_event_line).map(event => event.event_id);
  const requested = entries ?? marked;
  const eventLineIds = [...new Set(requested.map(id => owner.get(id) ?? id)
    .filter(id => queues.some(tree => tree.tree_id === id)))];
  if (!eventLineIds.length) eventLineIds.push(...roots);
  const selectedTrees = new Set(eventLineIds);
  for (const tree of queues) tree.is_event_line = selectedTrees.has(tree.tree_id);
  const lineEntries = new Set(eventLineIds.flatMap(id => {
    const first = queues.find(tree => tree.tree_id === id)?.event_ids[0];
    return first ? [first] : [];
  }));
  const book: EventTreeListResponse = { ...facts,
    events: facts.events.map(event => ({ ...event, is_event_line: lineEntries.has(event.event_id) })),
    event_line_ids: eventLineIds, queues, queue_references: references,
    organization_status: status ?? (eventLineIds.length ? "ready" : "pending_diagnosis"),
    counts: { event_lines: eventLineIds.length, trees: queues.length, tree_references: references.length,
      all_events: input.events.length, outcomes: input.outcomes.length, relations: input.relations.length,
      foreshadowing_actions: input.foreshadowing_actions.length }, next_cursor: null };
  indexEventQueues(book);
  return book;
}

export function fixtureEventDetail(book: EventTreeListResponse, eventId: string, runId = book.run_id): EventCardDetail {
  const index = indexEventQueues(book);
  const event = book.events.find(item => item.event_id === eventId)!;
  const tree = index.trees.get(index.eventTree.get(eventId)!)!;
  const position = tree.event_ids.indexOf(eventId);
  const parents = position ? [tree.event_ids[position - 1]] : book.queue_references
    .filter(edge => edge.child_tree_id === tree.tree_id)
    .flatMap(edge => {
      const last = index.trees.get(edge.parent_tree_id)!.event_ids.at(-1);
      return last ? [last] : [];
    });
  const children = position + 1 < tree.event_ids.length ? [tree.event_ids[position + 1]]
    : index.children.get(tree.tree_id)!.flatMap(id => {
        const first = index.trees.get(id)!.event_ids[0];
        return first ? [first] : [];
      });
  const roots = book.event_line_ids.filter(root => index.treeEvents(root).includes(eventId));
  const brief = (id: string) => { const value = book.events.find(item => item.event_id === id)!;
    return { event_id: id, title: value.title, event_type: value.event_type, status: value.status }; };
  return { ...event, kind: "event", run_id: runId, progress: "正在推进", characters: [],
    tree_id: tree.tree_id, tree_position: position, event_line_ids: roots,
    direct_parents: parents.map(brief), direct_children: children.map(brief),
    evidence: [{ chapter_id: event.chapter_id, paragraph_id: event.chapter_id }],
    source_chapters: [event.chapter_id], evidence_scope: "paragraph",
    relations: book.relations.filter(relation => relation.source_id === eventId || relation.target_id === eventId) };
}

/** 提供中段事件线入口、共享后代及未覆盖事件的完整夹具 */
export function selectedEventLineFixture(): EventTreeListResponse {
  const entries = ["a1", "b1", "c", "d", "e"];
  const identifiers = ["a0", "a1", "a2", "b0", "b1", "s0", "s1", "c", "d", "e",
    ...Array.from({ length: 10 }, (_, index) => `uncovered-${index}`)];
  const events = identifiers.map((id, index) => ({
    event_id: id, is_event_line: entries.includes(id), from: 1, to: 1,
    title: `事件 ${id}`, problem: `核对 ${id} 的线索`, summary: `事件 ${id} 的原文概要`,
    event_type: "调查", status: "进行中", first_text_position: index,
    chapter_id: 1, chapter_order: 1,
  }));
  const pairs = [["a0", "a1"], ["a1", "a2"], ["a2", "s0"], ["b0", "b1"], ["b1", "s0"], ["s0", "s1"]];
  return eventQueueFixture({
    run_id: "run-a", chapters: [{ chapter_id: 1, chapter_order: 1, title: "第一章" }], events,
    edges: pairs.map(([parent, child]) => ({ parent, child, reason: "原文支持的父子关系", evidence: [{ chapter_id: 1, paragraph_id: 1 }] })),
    event_line_ids: entries, organization_status: "ready", outcomes: [], relations: [], foreshadowing_actions: [],
  });
}
