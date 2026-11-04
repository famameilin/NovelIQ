import type { EventTreeListResponse } from "./narrativeTypes";

/** 校验独立树身份、成员覆盖、多父引用及事件线集合；空树合法 */
export function indexEventQueues(book: EventTreeListResponse) {
  const trees = new Map(book.queues.map(tree => [tree.tree_id, tree]));
  const events = new Set(book.events.map(event => event.event_id));
  const eventTree = new Map<string, string>();
  const children = new Map(book.queues.map(tree => [tree.tree_id, [] as string[]]));
  const incoming = new Map(book.queues.map(tree => [tree.tree_id, 0]));
  const invalid = () => { throw new Error("全书事件树响应不完整，身份、成员、引用或数量不一致"); };
  if (trees.size !== book.queues.length || events.size !== book.events.length) invalid();
  for (const tree of book.queues) {
    for (const eventId of tree.event_ids) {
      if (!events.has(eventId) || eventTree.has(eventId)) invalid();
      eventTree.set(eventId, tree.tree_id);
    }
  }
  if (eventTree.size !== events.size) invalid();
  const edges = new Set<string>();
  for (const edge of book.queue_references) {
    const key = JSON.stringify([edge.parent_tree_id, edge.child_tree_id]);
    if (!trees.has(edge.parent_tree_id) || !trees.has(edge.child_tree_id)
      || edge.parent_tree_id === edge.child_tree_id || edges.has(key)) invalid();
    edges.add(key);
    children.get(edge.parent_tree_id)!.push(edge.child_tree_id);
    incoming.set(edge.child_tree_id, incoming.get(edge.child_tree_id)! + 1);
  }
  const roots = book.queues.filter(tree => incoming.get(tree.tree_id) === 0).map(tree => tree.tree_id);
  if (new Set(book.event_line_ids).size !== book.event_line_ids.length
    || book.event_line_ids.some(id => !trees.has(id))) invalid();
  if (book.organization_status === "ready") {
    const selected = book.queues.filter(tree => tree.is_event_line).map(tree => tree.tree_id);
    if (selected.length !== book.event_line_ids.length || selected.some(id => !book.event_line_ids.includes(id))) invalid();
  }
  const order = [...roots];
  for (let index = 0; index < order.length; index++) {
    for (const child of children.get(order[index])!) {
      incoming.set(child, incoming.get(child)! - 1);
      if (!incoming.get(child)) order.push(child);
    }
  }
  if (order.length !== trees.size) invalid();
  const eventChildren = new Map<string, string[]>();
  for (const tree of book.queues) {
    tree.event_ids.forEach((id, position) => eventChildren.set(id,
      position + 1 < tree.event_ids.length
        ? [tree.event_ids[position + 1]]
        : children.get(tree.tree_id)!.flatMap(child => {
            const first = trees.get(child)!.event_ids[0];
            return first ? [first] : [];
          })));
  }
  const treeEvents = (treeId: string) => {
    if (!trees.has(treeId)) invalid();
    const found = new Set<string>();
    const pending = [treeId];
    while (pending.length) {
      const id = pending.pop()!;
      if (found.has(id)) continue;
      found.add(id);
      pending.push(...children.get(id)!);
    }
    return order.flatMap(id => trees.get(id)!.event_ids).filter(id => found.has(eventTree.get(id)!));
  };
  if (book.next_cursor !== null || book.counts.all_events !== events.size || book.counts.trees !== trees.size
    || book.counts.event_lines !== book.event_line_ids.length || book.counts.tree_references !== edges.size
    || book.counts.outcomes !== book.outcomes.length || book.counts.relations !== book.relations.length
    || book.counts.foreshadowing_actions !== book.foreshadowing_actions.length) invalid();
  return { trees, eventTree, children, order, treeEvents };
}

/** 同一业务事件在不同事件线中的位置身份 */
export function eventDisplayKey(lineId: string, eventId: string): string {
  return JSON.stringify([lineId, eventId]);
}
