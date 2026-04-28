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
  weightRange: { min: number; max: number };
  getNodeSize: (node: GraphNode) => number;
}

interface BuildForceGraphModelOptions {
  data: GraphData;
  relationFilter: Set<string>;
  appearanceCountMap?: Map<string, number>;
}

// 2026-04-23，任务：复杂度与耦合审查 P1
// 把数值映射逻辑抽成纯函数，供数据适配和布局/样式阶段复用。
export function mapValue(value: number, inMin: number, inMax: number, outMin: number, outMax: number): number {
  if (inMax === inMin) return (outMin + outMax) / 2;
  return ((value - inMin) / (inMax - inMin)) * (outMax - outMin) + outMin;
}

// 2026-04-23，任务：复杂度与耦合审查 P1
// 把深浅归一化逻辑从组件中抽离，便于节点着色和后续测试复用。
export function normalizeToRange(value: number, minVal: number, maxVal: number): number {
  if (maxVal <= minVal) return 0.3;
  return Math.max(0, Math.min(1, (value - minVal) / (maxVal - minVal)));
}

// 2026-04-23，任务：复杂度与耦合审查 P1
// G6 layout 的 nodeSize 回调依赖运行时配置，抽成纯函数后可避免 hook 内重复定义。
export function getConfiguredNodeSize(nodeCfg: unknown, fallback: number = NODE_SIZE_MIN): number {
  if (!nodeCfg || typeof nodeCfg !== "object") return fallback;
  const size = (nodeCfg as { size?: unknown }).size;
  return typeof size === "number" && Number.isFinite(size) ? size : fallback;
}

function buildNodeDegrees(data: GraphData): Map<string, number> {
  const degrees = new Map<string, number>();
  data.nodes.forEach((node) => degrees.set(node.entity_id, 0));
  data.edges.forEach((edge: GraphEdge) => {
    degrees.set(edge.source, (degrees.get(edge.source) || 0) + 1);
    degrees.set(edge.target, (degrees.get(edge.target) || 0) + 1);
  });
  return degrees;
}

function buildDegreeRange(nodeDegrees: Map<string, number>) {
  const values = Array.from(nodeDegrees.values());
  if (values.length === 0) return { min: 0, max: 1 };
  return { min: Math.min(...values), max: Math.max(...values) };
}

function buildWeightRange(edges: GraphEdge[]) {
  const weights = edges.map((edge) => edge.weight ?? 1).filter((weight): weight is number => weight !== undefined);
  if (weights.length === 0) return { min: 1, max: 1 };
  return { min: Math.min(...weights), max: Math.max(...weights) };
}

function buildNodeSizeResolver(
  nodeDegrees: Map<string, number>,
  degreeRange: { min: number; max: number },
  appearanceCountMap?: Map<string, number>
) {
  return (node: GraphNode): number => {
    if (appearanceCountMap && appearanceCountMap.size > 0) {
      let count = appearanceCountMap.get(node.entity_id);
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

    const degree = nodeDegrees.get(node.entity_id) || 0;
    if (degreeRange.max === degreeRange.min) return (NODE_SIZE_MIN + NODE_SIZE_MAX) / 2;
    return mapValue(degree, degreeRange.min, degreeRange.max, NODE_SIZE_MIN, NODE_SIZE_MAX);
  };
}

function adaptGraphData(data: GraphData, relationFilter: Set<string>) {
  const rawData = data as unknown as Record<string, unknown>;
  const links = (rawData.links || rawData.edges || []) as Record<string, unknown>[];
  if (relationFilter.size === 0) {
    return {
      nodes: data.nodes.map((node) => ({ ...node, id: node.entity_id })),
      edges: links,
    };
  }

  const filteredLinks = links.filter(
    (link: Record<string, unknown>) => !link.relation_type || relationFilter.has(String(link.relation_type))
  );
  const connectedIds = new Set<string>();
  filteredLinks.forEach((link) => {
    connectedIds.add(String(link.source));
    connectedIds.add(String(link.target));
  });
  const filteredNodes = data.nodes
    .filter((node) => connectedIds.has(node.entity_id))
    .map((node) => ({ ...node, id: node.entity_id }));

  return {
    nodes: filteredNodes,
    edges: filteredLinks,
  };
}

function buildOrderedLayoutNodes(nodes: ForceGraphNodeData[], edges: Record<string, unknown>[]) {
  const layoutDegrees = new Map<string, number>();
  nodes.forEach((node) => layoutDegrees.set(node.entity_id, 0));
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
    .filter((node) => (layoutDegrees.get(node.entity_id) || 0) > 1)
    .sort((left, right) => {
      const degreeDiff = (layoutDegrees.get(right.entity_id) || 0) - (layoutDegrees.get(left.entity_id) || 0);
      if (degreeDiff !== 0) return degreeDiff;
      return sortedByName(left, right);
    });
  const peripheralNodes = [...nodes]
    .filter((node) => (layoutDegrees.get(node.entity_id) || 0) === 1)
    .sort(sortedByName);
  const isolatedNodes = [...nodes]
    .filter((node) => (layoutDegrees.get(node.entity_id) || 0) === 0)
    .sort(sortedByName);

  return { connectedNodes, peripheralNodes, isolatedNodes };
}

// 2026-04-23，任务：复杂度与耦合审查 P1
// 将 ForceGraph 的过滤、度数统计和布局排序收口成单一适配步骤，避免组件混杂数据准备逻辑。
export function buildForceGraphModel({
  data,
  relationFilter,
  appearanceCountMap,
}: BuildForceGraphModelOptions): ForceGraphModel {
  const nodeDegrees = buildNodeDegrees(data);
  const degreeRange = buildDegreeRange(nodeDegrees);
  const weightRange = buildWeightRange(data.edges);
  const g6Data = adaptGraphData(data, relationFilter);
  const orderedLayoutNodes = buildOrderedLayoutNodes(g6Data.nodes, g6Data.edges);

  return {
    g6Data,
    orderedLayoutNodes,
    nodeDegrees,
    degreeRange,
    weightRange,
    getNodeSize: buildNodeSizeResolver(nodeDegrees, degreeRange, appearanceCountMap),
  };
}
