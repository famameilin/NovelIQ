import type { GraphData, GraphEdge, GraphNode } from "@/api/types";

/** 图谱总览的显示范围，all 表示不裁剪 */
export type GraphScope = "core" | "extended" | "all";

/** 各显示范围保留的节点上限，null 表示全部 */
export const GRAPH_SCOPE_LIMITS: Record<GraphScope, number | null> = {
  core: 30,
  extended: 100,
  all: null,
};

/** 聚焦视图保留的邻居上限 */
export const EGO_NEIGHBOR_LIMIT = 40;

const DEGREE_WEIGHT = 0.6;
const APPEARANCE_WEIGHT = 0.4;
const RELATION_NODE_SEPARATOR = "\u0000";

export interface GraphFocusOptions {
  scope: GraphScope;
  /** 空集合表示不限制实体类型 */
  entityTypes: Set<string>;
  focusEntityId: string | null;
  /** 空集合表示不限制关系类型 */
  relationTypes: Set<string>;
  appearanceCountMap?: Map<string, number>;
}

export interface GraphSubgraph {
  data: GraphData;
  focusNode: GraphNode | null;
  visibleNodeCount: number;
  /** 实体类型与关系类型过滤后、范围裁剪前的节点数 */
  eligibleNodeCount: number;
  visibleEdgeCount: number;
  eligibleEdgeCount: number;
  hiddenNodeCount: number;
  hiddenEdgeCount: number;
}

export interface RankedGraphNode {
  node: GraphNode;
  score: number;
  degree: number;
}

export interface GraphRelationItem {
  node: GraphNode;
  relationType: string;
  directionality: "directed" | "bidirectional";
  supportCount: number;
  isActive: boolean;
}

export interface GraphRelationGroup {
  relationType: string;
  items: GraphRelationItem[];
}

export interface EntityRelationSummary {
  groups: GraphRelationGroup[];
  /** 原始邻接边条数 */
  rawRelationCount: number;
  /** 按对端名与关系类型去重后的条数 */
  relationCount: number;
  /** 不同对端实体数 */
  entityCount: number;
}

function matchesEntityType(node: GraphNode, entityTypes: Set<string>): boolean {
  return entityTypes.size === 0 || entityTypes.has(node.entity_type);
}

function matchesRelationType(edge: GraphEdge, relationTypes: Set<string>): boolean {
  return relationTypes.size === 0 || relationTypes.has(edge.relation_type);
}

function readSupportCount(edge: GraphEdge): number {
  const raw = edge.attributes?.support_count;
  return typeof raw === "number" && Number.isFinite(raw) ? raw : 1;
}

function buildDegrees(edges: GraphEdge[]): Map<string, number> {
  const degrees = new Map<string, number>();
  edges.forEach((edge) => {
    const source = String(edge.source_entity_id);
    const target = String(edge.target_entity_id);
    degrees.set(source, (degrees.get(source) ?? 0) + 1);
    degrees.set(target, (degrees.get(target) ?? 0) + 1);
  });
  return degrees;
}

function readAppearanceCount(map: Map<string, number> | undefined, node: GraphNode): number {
  if (!map || map.size === 0) return 0;
  return map.get(String(node.entity_id)) ?? map.get(node.name) ?? 0;
}

function normalize(value: number, min: number, max: number): number {
  if (max <= min) return 0;
  return Math.max(0, Math.min(1, (value - min) / (max - min)));
}

/**
 * 按关系度数与登场次数给节点打分并降序排列
 * 简要说明：同分按中文名与实体主键排序，保证多次渲染顺序一致
 */
export function rankGraphNodes(
  nodes: GraphNode[],
  edges: GraphEdge[],
  appearanceCountMap?: Map<string, number>,
): RankedGraphNode[] {
  const degrees = buildDegrees(edges);
  const appearances = nodes.map((node) => readAppearanceCount(appearanceCountMap, node));
  const degreeValues = nodes.map((node) => degrees.get(String(node.entity_id)) ?? 0);
  const degreeRange = degreeValues.length
    ? { min: Math.min(...degreeValues), max: Math.max(...degreeValues) }
    : { min: 0, max: 0 };
  const appearanceRange = appearances.length
    ? { min: Math.min(...appearances), max: Math.max(...appearances) }
    : { min: 0, max: 0 };

  const ranked = nodes.map((node, index) => {
    const degree = degreeValues[index];
    const degreeScore = normalize(degree, degreeRange.min, degreeRange.max);
    const appearanceScore = normalize(appearances[index], appearanceRange.min, appearanceRange.max);
    const score =
      appearanceRange.max > appearanceRange.min
        ? degreeScore * DEGREE_WEIGHT + appearanceScore * APPEARANCE_WEIGHT
        : degreeScore;
    return { node, score: Math.round(score * 1e6) / 1e6, degree };
  });

  return ranked.sort((left, right) => {
    if (right.score !== left.score) return right.score - left.score;
    const byName = left.node.name.localeCompare(right.node.name, "zh-CN");
    if (byName !== 0) return byName;
    return String(left.node.entity_id).localeCompare(String(right.node.entity_id));
  });
}

/** 统计各实体类型的节点数，按数量降序 */
export function countEntitiesByType(nodes: GraphNode[]): Array<{ type: string; count: number }> {
  const counts = new Map<string, number>();
  nodes.forEach((node) => {
    counts.set(node.entity_type, (counts.get(node.entity_type) ?? 0) + 1);
  });
  return Array.from(counts.entries())
    .map(([type, count]) => ({ type, count }))
    .sort((left, right) => right.count - left.count || left.type.localeCompare(right.type));
}

function emptySubgraph(data: GraphData, focusNode: GraphNode | null): GraphSubgraph {
  return {
    data: { ...data, nodes: [], edges: [] },
    focusNode,
    visibleNodeCount: 0,
    eligibleNodeCount: 0,
    visibleEdgeCount: 0,
    eligibleEdgeCount: 0,
    hiddenNodeCount: 0,
    hiddenEdgeCount: 0,
  };
}

function buildOverviewSubgraph(
  data: GraphData,
  eligibleNodes: GraphNode[],
  eligibleEdges: GraphEdge[],
  options: GraphFocusOptions,
): GraphSubgraph {
  const limit = GRAPH_SCOPE_LIMITS[options.scope];
  const ranked = rankGraphNodes(eligibleNodes, eligibleEdges, options.appearanceCountMap);
  const selected = limit === null ? ranked.map((entry) => entry.node) : ranked.slice(0, limit).map((entry) => entry.node);
  const selectedIds = new Set(selected.map((node) => String(node.entity_id)));
  const visibleEdges = eligibleEdges.filter(
    (edge) =>
      selectedIds.has(String(edge.source_entity_id)) && selectedIds.has(String(edge.target_entity_id)),
  );

  return {
    data: { ...data, nodes: selected, edges: visibleEdges },
    focusNode: null,
    visibleNodeCount: selected.length,
    eligibleNodeCount: eligibleNodes.length,
    visibleEdgeCount: visibleEdges.length,
    eligibleEdgeCount: eligibleEdges.length,
    hiddenNodeCount: Math.max(eligibleNodes.length - selected.length, 0),
    hiddenEdgeCount: Math.max(eligibleEdges.length - visibleEdges.length, 0),
  };
}

function buildEgoSubgraph(
  data: GraphData,
  nodeById: Map<string, GraphNode>,
  eligibleEdges: GraphEdge[],
  options: GraphFocusOptions,
): GraphSubgraph {
  const focusId = String(options.focusEntityId);
  const focusNode = nodeById.get(focusId) ?? null;
  if (!focusNode) return emptySubgraph(data, null);

  const incidentEdges = eligibleEdges.filter(
    (edge) => String(edge.source_entity_id) === focusId || String(edge.target_entity_id) === focusId,
  );

  const neighborWeights = new Map<string, number>();
  incidentEdges.forEach((edge) => {
    const source = String(edge.source_entity_id);
    const target = String(edge.target_entity_id);
    const other = source === focusId ? target : source;
    if (other === focusId) return;
    neighborWeights.set(other, (neighborWeights.get(other) ?? 0) + Math.max(readSupportCount(edge), 1));
  });

  const rankedNeighbors = Array.from(neighborWeights.entries())
    .flatMap(([entityId, weight]) => {
      const node = nodeById.get(entityId);
      return node ? [{ node, weight }] : [];
    })
    .sort((left, right) => {
      if (right.weight !== left.weight) return right.weight - left.weight;
      const leftSeen = left.node.last_seen_chapter ?? 0;
      const rightSeen = right.node.last_seen_chapter ?? 0;
      if (rightSeen !== leftSeen) return rightSeen - leftSeen;
      return left.node.name.localeCompare(right.node.name, "zh-CN");
    });

  const visibleNeighbors = rankedNeighbors.slice(0, EGO_NEIGHBOR_LIMIT);
  const visibleIds = new Set<string>([focusId, ...visibleNeighbors.map((entry) => String(entry.node.entity_id))]);
  const visibleEdges = incidentEdges.filter((edge) => {
    const other =
      String(edge.source_entity_id) === focusId
        ? String(edge.target_entity_id)
        : String(edge.source_entity_id);
    return visibleIds.has(other);
  });

  const visibleNodes = [focusNode, ...visibleNeighbors.map((entry) => entry.node)];

  return {
    data: { ...data, nodes: visibleNodes, edges: visibleEdges },
    focusNode,
    visibleNodeCount: visibleNodes.length,
    eligibleNodeCount: data.nodes.length,
    visibleEdgeCount: visibleEdges.length,
    eligibleEdgeCount: incidentEdges.length,
    hiddenNodeCount: Math.max(rankedNeighbors.length - visibleNeighbors.length, 0),
    hiddenEdgeCount: Math.max(incidentEdges.length - visibleEdges.length, 0),
  };
}

/**
 * 按实体类型、关系类型、显示范围与焦点构建实际渲染的子图
 * 简要说明：先过滤类型，再按范围取点或取焦点一圈邻居，最后只保留两端都在子图内的边
 */
export function buildGraphSubgraph(data: GraphData, options: GraphFocusOptions): GraphSubgraph {
  const nodeById = new Map(data.nodes.map((node) => [String(node.entity_id), node]));
  const eligibleNodes = data.nodes.filter((node) => matchesEntityType(node, options.entityTypes));
  const eligibleIds = new Set(eligibleNodes.map((node) => String(node.entity_id)));

  const eligibleEdges = data.edges.filter((edge) => {
    if (!matchesRelationType(edge, options.relationTypes)) return false;
    return (
      eligibleIds.has(String(edge.source_entity_id)) && eligibleIds.has(String(edge.target_entity_id))
    );
  });

  if (options.focusEntityId && eligibleIds.has(String(options.focusEntityId))) {
    const subgraph = buildEgoSubgraph(data, nodeById, eligibleEdges, options);
    return {
      ...subgraph,
      eligibleNodeCount: eligibleNodes.length,
    };
  }

  return buildOverviewSubgraph(data, eligibleNodes, eligibleEdges, options);
}

/**
 * 汇总指定实体的全部邻接关系并按关系类型分组
 * 简要说明：按对端名去重同名别名，组内按支持次数与最后出现章节排序
 */
export function buildEntityRelationSummary(
  data: GraphData,
  entityId: string | null,
): EntityRelationSummary {
  const empty: EntityRelationSummary = { groups: [], rawRelationCount: 0, relationCount: 0, entityCount: 0 };
  if (!entityId) return empty;

  const targetId = String(entityId);
  const nodeById = new Map(data.nodes.map((node) => [String(node.entity_id), node]));
  const accumulators = new Map<string, GraphRelationItem>();
  let rawRelationCount = 0;

  data.edges.forEach((edge) => {
    const source = String(edge.source_entity_id);
    const target = String(edge.target_entity_id);
    if (source !== targetId && target !== targetId) return;
    rawRelationCount += 1;

    const otherId = source === targetId ? target : source;
    const otherNode = nodeById.get(otherId);
    if (!otherNode) return;

    const key = `${otherNode.name}${RELATION_NODE_SEPARATOR}${edge.relation_type}`;
    const existing = accumulators.get(key);
    const supportCount = readSupportCount(edge);
    if (existing) {
      existing.supportCount += supportCount;
      existing.isActive = existing.isActive || edge.is_active;
      return;
    }
    accumulators.set(key, {
      node: otherNode,
      relationType: edge.relation_type,
      directionality: edge.directionality,
      supportCount,
      isActive: edge.is_active,
    });
  });

  const byType = new Map<string, GraphRelationItem[]>();
  accumulators.forEach((item) => {
    const bucket = byType.get(item.relationType);
    if (bucket) {
      bucket.push(item);
    } else {
      byType.set(item.relationType, [item]);
    }
  });

  const groups: GraphRelationGroup[] = Array.from(byType.entries())
    .map(([relationType, items]) => ({
      relationType,
      items: items.sort((left, right) => {
        if (right.supportCount !== left.supportCount) return right.supportCount - left.supportCount;
        const leftSeen = left.node.last_seen_chapter ?? 0;
        const rightSeen = right.node.last_seen_chapter ?? 0;
        if (rightSeen !== leftSeen) return rightSeen - leftSeen;
        return left.node.name.localeCompare(right.node.name, "zh-CN");
      }),
    }))
    .sort(
      (left, right) =>
        right.items.length - left.items.length || left.relationType.localeCompare(right.relationType, "zh-CN"),
    );

  const entityNames = new Set<string>();
  accumulators.forEach((item) => entityNames.add(item.node.name));

  return {
    groups,
    rawRelationCount,
    relationCount: accumulators.size,
    entityCount: entityNames.size,
  };
}
