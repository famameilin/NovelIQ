/**
 * 事件森林「树内图外」布局视图（契约 v3）
 *
 * 2026-08-19 P3：把后端树视图（event_trees + causal_edges）组装成可渲染的
 * 树列表与跨树因果边；纯函数，便于单测（不引 G6 画布）。
 */
import type {
  EventEdgeResponse,
  EventForestResponse,
  EventNodeResponse,
  EventTreeResponse,
} from "@/api/types";

export interface EventTreeBranchGroup {
  target: EventNodeResponse;
  branch: EventNodeResponse[];
}

export interface EventTreeViewItem {
  treeId: string;
  root: EventNodeResponse;
  mainChain: EventNodeResponse[];
  secondaryGroups: EventTreeBranchGroup[];
  chapterRange: string;
}

export interface EventForestView {
  nodesById: Map<string, EventNodeResponse>;
  trees: EventTreeViewItem[];
  crossTreeEdges: EventEdgeResponse[];
}

export function buildEventForestView(data: EventForestResponse): EventForestView {
  const nodesById = new Map(data.event_nodes.map((node) => [node.event_id, node]));
  const treeIdByNodeId = new Map(data.event_nodes.map((node) => [node.event_id, node.tree_id]));
  const trees = data.event_trees
    .map((tree) => toTreeViewItem(tree, nodesById))
    .filter((item): item is EventTreeViewItem => item !== null);
  const crossTreeEdges = data.causal_edges.filter((edge) => {
    const from = treeIdByNodeId.get(edge.source_event_id);
    const to = treeIdByNodeId.get(edge.target_event_id);
    return from !== undefined && to !== undefined && from !== to;
  });
  return { nodesById, trees, crossTreeEdges };
}

function toTreeViewItem(
  tree: EventTreeResponse,
  nodesById: Map<string, EventNodeResponse>,
): EventTreeViewItem | null {
  const mainChain = tree.main_chain
    .map((id) => nodesById.get(id))
    .filter((node): node is EventNodeResponse => node !== undefined);
  if (mainChain.length === 0) {
    return null;
  }
  const root = nodesById.get(tree.root_event_id) ?? mainChain[0];
  const secondaryGroups = tree.secondary_groups
    .map((group) => ({
      target: nodesById.get(group.target_event_id),
      branch: group.branch
        .map((id) => nodesById.get(id))
        .filter((node): node is EventNodeResponse => node !== undefined),
    }))
    .filter(
      (group): group is EventTreeBranchGroup =>
        group.target !== undefined && group.branch.length > 0,
    );
  const chapterRange =
    tree.chapter_ids.length === 0
      ? ""
      : `第 ${tree.chapter_ids[0]}–${tree.chapter_ids[tree.chapter_ids.length - 1]} 章`;
  return { treeId: tree.tree_id, root, mainChain, secondaryGroups, chapterRange };
}
