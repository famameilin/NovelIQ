import type { EventTreeEvent, EventTreeListResponse } from "@/api/narrativeTypes";
import { indexEventQueues } from "@/api/eventQueues";

export interface EventLineNode {
  eventId: string;
  title: string;
  displayTitle: string;
  chapterOrder: number;
  eventType: string;
  childCount: number;
  isRoot: boolean;
  /** 仅为深链目标补入的节点，本身不是分支入口 */
  focusOnly: boolean;
  /** 该节点所属的事件，按全书顺序 */
  eventIds: string[];
}

export interface EventLine {
  id: string;
  title: string;
  objective: string;
  colorIndex: number;
  eventIds: string[];
  treeIds: string[];
  nodes: EventLineNode[];
  events: EventTreeEvent[];
  eventCount: number;
}

export interface EventLineBook {
  lines: EventLine[];
  lineByEvent: Map<string, EventLine[]>;
  lineByTree: Map<string, EventLine[]>;
}

function displayTitle(title: string): string {
  const cleaned = title.replace(/^第[一二三四五六七八九十百千\d]+章[：:\s]*/u, "").replace(/\s+/g, " ").trim();
  return cleaned.length > 8 ? `${cleaned.slice(0, 8)}…` : cleaned;
}

function lineNodes(roots: EventTreeEvent[], events: EventTreeEvent[], childrenOf: Map<string, string[]>, focusEventId?: string, branchHeadIds?: string[]): EventLineNode[] {
  const rootIds = new Set(roots.map(event => event.event_id));
  const byId = new Map(events.map(event => [event.event_id, event]));
  const positionOf = new Map(events.map((event, position) => [event.event_id, position]));
  const heads = (branchHeadIds ?? [])
    .map(id => byId.get(id))
    .filter((event): event is EventTreeEvent => !!event && !rootIds.has(event.event_id));
  // 关键节点为该线全部分支入口，不按可视区截断；没有分支入口时退回本线首尾
  const candidates = heads.length ? heads : [events[0], events.at(-1)].filter((event): event is EventTreeEvent => !!event);
  const selectedIds = new Set<string>();
  for (const event of candidates) selectedIds.add(event.event_id);
  // 深链目标不在关键节点时补入，保证画布上可见且可选中
  if (focusEventId && !selectedIds.has(focusEventId)) {
    const event = events.find(item => item.event_id === focusEventId);
    if (event) selectedIds.add(event.event_id);
  }
  const nodes: EventLineNode[] = events
    .filter(event => selectedIds.has(event.event_id))
    .map(event => ({
      eventId: event.event_id, title: event.title, displayTitle: displayTitle(event.title),
      chapterOrder: event.chapter_order, eventType: event.event_type,
      childCount: (childrenOf.get(event.event_id) ?? []).length, isRoot: rootIds.has(event.event_id),
      focusOnly: !!focusEventId && focusEventId === event.event_id && !candidates.some(item => item.event_id === event.event_id),
      eventIds: [],
    }));
  // 每个节点所属事件为本节点到下一节点之间的事件，首尾相接覆盖整条线
  for (let index = 0; index < nodes.length; index++) {
    const start = positionOf.get(nodes[index].eventId) ?? 0;
    const end = index + 1 < nodes.length ? positionOf.get(nodes[index + 1].eventId) ?? events.length : events.length;
    nodes[index].eventIds = events.slice(start, end).map(event => event.event_id);
  }
  return nodes;
}
export function buildEventLines(book: EventTreeListResponse, focusEventId?: string): EventLineBook {
  const index = indexEventQueues(book);
  const byId = new Map(book.events.map(event => [event.event_id, event]));
  const childrenOf = new Map<string, string[]>();
  for (const tree of book.queues) {
    tree.event_ids.forEach((id, position) => {
      childrenOf.set(id, position + 1 < tree.event_ids.length
        ? [tree.event_ids[position + 1]]
        : [...index.children.get(tree.tree_id)!].flatMap(child => {
            const first = index.trees.get(child)!.event_ids[0];
            return first ? [first] : [];
          }));
    });
  }
  const facts = book.event_line_ids.map(lineTreeId => {
    const tree = index.trees.get(lineTreeId)!;
    const identifiers = index.treeEvents(lineTreeId);
    const treeSet = new Set(identifiers.map(id => index.eventTree.get(id)!));
    const queueIds = index.order.filter(id => treeSet.has(id));
    const events = identifiers.map(id => byId.get(id)!);
    const own = tree.event_ids.flatMap(id => { const event = byId.get(id); return event ? [event] : []; });
    const head = own[0] ?? events[0];
    const branchHeadIds = (index.children.get(lineTreeId) ?? []).flatMap(id => {
      const first = index.trees.get(id)!.event_ids[0];
      return first ? [first] : [];
    });
    return { id: lineTreeId, tree, head, queueIds, events, branchHeadIds };
  });
  // 所有可达事件树都参与事件线，关键节点不按共享次数或可视区裁剪
  const lines = facts.map((fact, colorIndex) => ({
    id: fact.id, title: displayTitle(fact.tree.line_name ?? fact.tree.title), objective: fact.tree.description, colorIndex,
    treeIds: fact.queueIds, eventIds: fact.events.map(event => event.event_id), events: fact.events,
    nodes: lineNodes(fact.head ? [fact.head] : [], fact.events, childrenOf, focusEventId, fact.branchHeadIds),
    eventCount: fact.events.length,
  }));
  const lineByEvent = new Map<string, EventLine[]>();
  const lineByTree = new Map<string, EventLine[]>();
  for (const line of lines) {
    for (const id of line.eventIds) lineByEvent.set(id, [...(lineByEvent.get(id) ?? []), line]);
    for (const id of line.treeIds) lineByTree.set(id, [...(lineByTree.get(id) ?? []), line]);
  }
  return { lines, lineByEvent, lineByTree };
}
