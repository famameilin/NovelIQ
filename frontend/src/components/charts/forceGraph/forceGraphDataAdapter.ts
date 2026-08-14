import type { GraphData, GraphEdge, GraphNode } from "@/api/types";
import type { GraphNodeObject } from "@/components/charts/forceGraphTypes";

export const NODE_SIZE_MIN = 44;
export const NODE_SIZE_MAX = 64;
export const LINK_WIDTH_MIN = 1.5;
export const LINK_WIDTH_MAX = 6;

export interface ForceGraphNodeData extends GraphNodeObject {
  id: string;
}

export interface ForceGraphModel {
  g6Data: {
    nodes: ForceGraphNodeData[];
    edges: Record<string, unknown>[];
  };
  orderedLayoutNodes: {
    connectedNodes: ForceGraphNodeData[];
    peripheralNodes: ForceGraphNodeData[];
    isolatedNodes: ForceGraphNodeData[];
  };
  nodeDegrees: Map<string, number>;
  degreeRange: { min: number; max: number };
  getNodeSize: (node: GraphNode) => number;
}

interface BuildForceGraphModelOptions {
  data: GraphData;
  relationFilter: Set<string>;
  appearanceCountMap?: Map<string, number>;
}

// 2026-04-23，任务：复杂度与耦合审查 P1
// 把数值映射逻辑抽成纯函数，供数据适配和布局/样式阶段复用
export function mapValue(value: number, inMin: number, inMax: number, outMin: number, outMax: number): number {
  if (inMax === inMin) return (outMin + outMax) / 2;
  return ((value - inMin) / (inMax - inMin)) * (outMax - outMin) + outMin;
}

// 2026-04-23，任务：复杂度与耦合审查 P1
// 把深浅归一化逻辑从组件中抽离，便于节点着色和后续测试复用
export function normalizeToRange(value: number, minVal: number, maxVal: number): number {
  if (maxVal <= minVal) return 0.3;
  return Math.max(0, Math.min(1, (value - minVal) / (maxVal - minVal)));
}

// 2026-04-23，任务：复杂度与耦合审查 P1
// G6 layout 的 nodeSize 回调依赖运行时配置，抽成纯函数后可避免 hook 内重复定义
export function getConfiguredNodeSize(nodeCfg: unknown, fallback: number = NODE_SIZE_MIN): number {
  if (!nodeCfg || typeof nodeCfg !== "object") return fallback;
  const size = (nodeCfg as { size?: unknown }).size;
  return typeof size === "number" && Number.isFinite(size) ? size : fallback;
}

function buildNodeDegrees(data: GraphData): Map<string, number> {
  const degrees = new Map<string, number>();
  data.nodes.forEach((node) => degrees.set(String(node.entity_id), 0));
  data.edges.forEach((edge: GraphEdge) => {
    const sourceId = String(edge.source_entity_id);
    const targetId = String(edge.target_entity_id);
    degrees.set(sourceId, (degrees.get(sourceId) || 0) + 1);
    degrees.set(targetId, (degrees.get(targetId) || 0) + 1);
  });
  return degrees;
}

function buildDegreeRange(nodeDegrees: Map<string, number>) {
  const values = Array.from(nodeDegrees.values());
  if (values.length === 0) return { min: 0, max: 1 };
  return { min: Math.min(...values), max: Math.max(...values) };
}

function buildNodeSizeResolver(
  nodeDegrees: Map<string, number>,
  degreeRange: { min: number; max: number },
  appearanceCountMap?: Map<string, number>
) {
  return (node: GraphNode): number => {
    if (appearanceCountMap && appearanceCountMap.size > 0) {
      let count = appearanceCountMap.get(String(node.entity_id));
      if (count === undefined) {
        count = appearanceCountMap.get(node.name);
      }
      const finalCount = count || 0;
      const counts = Array.from(appearanceCountMap.values()) as number[];
      if (counts.length === 0) return (NODE_SIZE_MIN + NODE_SIZE_MAX) / 2;
      const minCount = Math.min(...counts);
      const maxCount = Math.max(...counts);
      if (maxCount === minCount) return (NODE_SIZE_MIN + NODE_SIZE_MAX) / 2;
      return mapValue(finalCount, minCount, maxCount, NODE_SIZE_MIN, NODE_SIZE_MAX);
    }

    const degree = nodeDegrees.get(String(node.entity_id)) || 0;
    if (degreeRange.max === degreeRange.min) return (NODE_SIZE_MIN + NODE_SIZE_MAX) / 2;
    return mapValue(degree, degreeRange.min, degreeRange.max, NODE_SIZE_MIN, NODE_SIZE_MAX);
  };
}

function adaptGraphData(data: GraphData, relationFilter: Set<string>) {
  const edges = data.edges.map((edge) => ({
    source: String(edge.source_entity_id),
    target: String(edge.target_entity_id),
    relation_id: edge.relation_id,
    relation_type: edge.relation_type,
    directionality: edge.directionality,
    is_active: edge.is_active,
  }));
  if (relationFilter.size === 0) {
    return {
      nodes: data.nodes.map((node) => ({ ...node, id: String(node.entity_id) })),
      edges,
    };
  }

  const filteredLinks = edges.filter((edge) => relationFilter.has(edge.relation_type));
  const connectedIds = new Set<string>();
  filteredLinks.forEach((edge) => {
    connectedIds.add(edge.source);
    connectedIds.add(edge.target);
  });
  const filteredNodes = data.nodes
    .filter((node) => connectedIds.has(String(node.entity_id)))
    .map((node) => ({ ...node, id: String(node.entity_id) }));

  return {
    nodes: filteredNodes,
    edges: filteredLinks,
  };
}

function buildOrderedLayoutNodes(nodes: ForceGraphNodeData[], edges: Record<string, unknown>[]) {
  const layoutDegrees = new Map<string, number>();
  nodes.forEach((node) => layoutDegrees.set(String(node.entity_id), 0));
  edges.forEach((edge) => {
    const source = String(edge.source ?? "");
    const target = String(edge.target ?? "");
    if (layoutDegrees.has(source)) {
      layoutDegrees.set(source, (layoutDegrees.get(source) || 0) + 1);
    }
    if (layoutDegrees.has(target)) {
      layoutDegrees.set(target, (layoutDegrees.get(target) || 0) + 1);
    }
  });

  const sortedByName = (left: ForceGraphNodeData, right: ForceGraphNodeData) => left.name.localeCompare(right.name, "zh-CN");
  const connectedNodes = [...nodes]
    .filter((node) => (layoutDegrees.get(String(node.entity_id)) || 0) > 1)
    .sort((left, right) => {
      const degreeDiff =
        (layoutDegrees.get(String(right.entity_id)) || 0) - (layoutDegrees.get(String(left.entity_id)) || 0);
      if (degreeDiff !== 0) return degreeDiff;
      return sortedByName(left, right);
    });
  const peripheralNodes = [...nodes]
    .filter((node) => (layoutDegrees.get(String(node.entity_id)) || 0) === 1)
    .sort(sortedByName);
  const isolatedNodes = [...nodes]
    .filter((node) => (layoutDegrees.get(String(node.entity_id)) || 0) === 0)
    .sort(sortedByName);

  return { connectedNodes, peripheralNodes, isolatedNodes };
}

// 2026-04-23，任务：复杂度与耦合审查 P1
// 将 ForceGraph 的过滤、度数统计和布局排序收口成单一适配步骤，避免组件混杂数据准备逻辑
export function buildForceGraphModel({
  data,
  relationFilter,
  appearanceCountMap,
}: BuildForceGraphModelOptions): ForceGraphModel {
  const nodeDegrees = buildNodeDegrees(data);
  const degreeRange = buildDegreeRange(nodeDegrees);
  const g6Data = adaptGraphData(data, relationFilter);
  const orderedLayoutNodes = buildOrderedLayoutNodes(g6Data.nodes, g6Data.edges);

  return {
    g6Data,
    orderedLayoutNodes,
    nodeDegrees,
    degreeRange,
    getNodeSize: buildNodeSizeResolver(nodeDegrees, degreeRange, appearanceCountMap),
  };
}
