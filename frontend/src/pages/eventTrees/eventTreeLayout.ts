import type { EventForestNode, EventForestTree } from "@/api/types";

export interface TreePoint { x: number; y: number }
export interface TreeConnection { source: string; target: string; kind: "main" | "secondary" }
export interface TreeSceneLayout {
  points: Map<string, TreePoint>;
  connections: TreeConnection[];
  unlinked: string[];
}

/**
 * 主链立为树干，旁支从正式标注中的真实父节点生长
 * 无法追溯到树干的节点仍可见，但不会得到推测出来的连线
 */
export function layoutEventTree(tree: EventForestTree, nodes: Map<string, EventForestNode>): TreeSceneLayout {
  const points = new Map<string, TreePoint>();
  const mainIds = tree.main_chain.filter((id) => nodes.has(id));
  const mainSet = new Set(mainIds);
  const secondaryIds = tree.secondary_groups.flatMap((group) => group.branch).filter((id) => nodes.has(id));
  const secondarySet = new Set(secondaryIds);
  const siblingIndex = new Map<string, number>();
  for (const group of tree.secondary_groups) {
    group.branch.forEach((id, index) => siblingIndex.set(id, index));
  }

  mainIds.forEach((id, index) => {
    points.set(id, {
      x: 360 + Math.sin(index * 0.8) * 5,
      y: mainIds.length === 1 ? 285 : 490 - index * 415 / (mainIds.length - 1),
    });
  });

  function reachesMain(id: string): boolean {
    const visited = new Set([id]);
    let parentId = nodes.get(id)?.parent_event_id;
    while (parentId) {
      if (mainSet.has(parentId)) return true;
      if (!secondarySet.has(parentId) || visited.has(parentId)) return false;
      visited.add(parentId);
      parentId = nodes.get(parentId)?.parent_event_id;
    }
    return false;
  }

  const pending = new Set(secondaryIds.filter((id) => reachesMain(id)));
  for (let pass = 0; pass < secondaryIds.length && pending.size > 0; pass += 1) {
    let placed = false;
    for (const id of [...pending]) {
      const parentId = nodes.get(id)?.parent_event_id;
      const parent = parentId ? points.get(parentId) : undefined;
      if (!parent) continue;
      const index = siblingIndex.get(id) ?? 0;
      const side = index % 2 === 0 ? -1 : 1;
      const lane = Math.floor(index / 2);
      const outward = 100 + lane * 52;
      let x = parent.x + side * outward;
      if (x < 45 || x > 675) x = parent.x - side * outward;
      x = Math.max(45, Math.min(675, x));
      const verticalDirection = parent.y < 135 ? 1 : -1;
      let y = Math.max(48, Math.min(505, parent.y + verticalDirection * (20 + lane * 19)));
      // 同一片树冠里以离父节点最近的空位放叶子，防止多个旁支遮住彼此
      for (let attempt = 0; attempt < 24; attempt += 1) {
        const overlap = [...points.values()].some((point) => Math.hypot(point.x - x, point.y - y) < 24);
        if (!overlap) break;
        y = Math.max(48, Math.min(505, y + (attempt % 2 === 0 ? -1 : 1) * (22 + Math.floor(attempt / 2) * 12)));
      }
      points.set(id, { x, y });
      pending.delete(id);
      placed = true;
    }
    if (!placed) break;
  }

  const unlinked = secondaryIds.filter((id) => !points.has(id));
  unlinked.forEach((id, index) => {
    points.set(id, { x: 55 + (index % 13) * 50, y: 535 - Math.floor(index / 13) * 30 });
  });

  const connections: TreeConnection[] = [];
  for (const id of [...mainIds, ...secondaryIds]) {
    const node = nodes.get(id);
    if (!node?.parent_event_id || !points.has(node.parent_event_id) || unlinked.includes(id)) continue;
    if (node.tree_id !== nodes.get(node.parent_event_id)?.tree_id) continue;
    connections.push({
      source: node.parent_event_id,
      target: id,
      kind: node.cause_role === "secondary" ? "secondary" : "main",
    });
  }
  return { points, connections, unlinked };
}

export function treeNodeIds(tree: EventForestTree): string[] {
  return [...tree.main_chain, ...tree.secondary_groups.flatMap((group) => group.branch)];
}

export function treeNodeCount(tree: EventForestTree): number {
  return treeNodeIds(tree).length;
}
