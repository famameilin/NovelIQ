import type { GraphNode } from "@/api/types";

import type { ForceGraphModel, ForceGraphNodeData } from "./forceGraphDataAdapter";

export const NODE_SPACING_MIN = 14;
export const FIT_VIEW_PADDING = 24;
const INNER_RING_RATIO = 0.18;
const OUTER_RING_RATIO = 0.46;
const PERIPHERAL_RING_RATIO = 0.54;
const ISOLATED_RING_RATIO = 0.62;

// 2026-04-23，任务：复杂度与耦合审查 P1
// 把 G6 力导布局配置独立出来，避免组件生命周期和布局参数相互缠绕
export function buildForceLayoutConfig(width: number, height: number, nodeCount: number) {
  const densityScale = nodeCount >= 30 ? 1.25 : nodeCount >= 20 ? 1.1 : 1;
  return {
    type: "force" as const,
    center: [width / 2, height / 2] as [number, number],
    preventOverlap: true,
    collideStrength: 0.9,
    linkDistance: Math.round(165 * densityScale),
    nodeStrength: Math.round(-210 * densityScale),
    edgeStrength: nodeCount >= 30 ? 0.06 : 0.1,
    alphaDecay: 0.05,
    alphaMin: 0.002,
  };
}

function positionNodesInRings(
  orderedNodes: ForceGraphModel["orderedLayoutNodes"],
  width: number,
  height: number,
  getNodeSize: (node: GraphNode) => number
) {
  const centerX = width / 2;
  const centerY = height / 2;
  const shorterSide = Math.min(width, height);
  const coreNodeCount = orderedNodes.connectedNodes.length;
  const ringCount = Math.max(2, Math.ceil(Math.sqrt(Math.max(coreNodeCount, 1) / 2)));
  const nodesPerRing = Math.max(5, Math.ceil(Math.max(coreNodeCount, 1) / ringCount));
  const innerRadius = shorterSide * INNER_RING_RATIO;
  const maxRadius = shorterSide * OUTER_RING_RATIO;
  const ringStep = ringCount > 1 ? Math.max(42, (maxRadius - innerRadius) / (ringCount - 1)) : 0;
  const peripheralRadius = shorterSide * PERIPHERAL_RING_RATIO;
  const isolatedRadius = shorterSide * ISOLATED_RING_RATIO;

  const positionedNodes = new Map<string, ForceGraphNodeData & { size: number; x: number; y: number }>();

  orderedNodes.connectedNodes.forEach((node, index) => {
    const ringIndex = Math.floor(index / nodesPerRing);
    const indexInRing = index % nodesPerRing;
    const nodesInCurrentRing = Math.max(1, Math.min(nodesPerRing, coreNodeCount - ringIndex * nodesPerRing));
    const angle = (2 * Math.PI * indexInRing) / nodesInCurrentRing + ringIndex * 0.45 + (Math.random() - 0.5) * 0.12;
    const baseRadius = Math.min(maxRadius, innerRadius + ringIndex * ringStep);
    const radius = Math.min(maxRadius, baseRadius + (Math.random() - 0.5) * 18);
    positionedNodes.set(String(node.entity_id), {
      ...node,
      size: getNodeSize(node),
      x: centerX + Math.cos(angle) * radius,
      y: centerY + Math.sin(angle) * radius,
    });
  });

  orderedNodes.peripheralNodes.forEach((node, index) => {
    const count = Math.max(orderedNodes.peripheralNodes.length, 1);
    const angle = (2 * Math.PI * index) / count + Math.PI / 10 + (Math.random() - 0.5) * 0.08;
    const radius = peripheralRadius + (Math.random() - 0.5) * 14;
    positionedNodes.set(String(node.entity_id), {
      ...node,
      size: getNodeSize(node),
      x: centerX + Math.cos(angle) * radius,
      y: centerY + Math.sin(angle) * radius,
    });
  });

  orderedNodes.isolatedNodes.forEach((node, index) => {
    const count = Math.max(orderedNodes.isolatedNodes.length, 1);
    const angle = (2 * Math.PI * index) / count - Math.PI / 6 + (Math.random() - 0.5) * 0.05;
    const radius = isolatedRadius + (Math.random() - 0.5) * 10;
    positionedNodes.set(String(node.entity_id), {
      ...node,
      size: getNodeSize(node),
      x: centerX + Math.cos(angle) * radius,
      y: centerY + Math.sin(angle) * radius,
    });
  });

  return { centerX, centerY, positionedNodes };
}

// 2026-04-23，任务：复杂度与耦合审查 P1
// 把初始布局坐标生成从 G6 生命周期中抽出，便于独立维护布局策略
export function buildInitialGraphPayload(model: ForceGraphModel, width: number, height: number) {
  const { centerX, centerY, positionedNodes } = positionNodesInRings(
    model.orderedLayoutNodes,
    width,
    height,
    model.getNodeSize
  );

  return {
    nodes: model.g6Data.nodes.map((node) => {
      const positionedNode = positionedNodes.get(String(node.entity_id));
      return (
        positionedNode ?? {
          ...node,
          size: model.getNodeSize(node),
          x: centerX,
          y: centerY,
        }
      );
    }),
    edges: model.g6Data.edges,
  };
}
