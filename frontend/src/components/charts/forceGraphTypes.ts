// ForceGraph 的 G6 运行时类型归属于图谱组件边界，避免污染后端 API contract 类型

import type {
  GraphData,
  GraphNode,
} from "@/api/types";

export interface GraphNodeObject extends GraphNode {
  id: string;
  x?: number;
  y?: number;
  vx?: number;
  vy?: number;
}

export interface ForceGraphProps {
  data: GraphData;
  onNodeClick: (node: GraphNodeObject) => void;
  searchQuery: string;
  relationFilter: Set<string>;
  appearanceCountMap?: Map<string, number>;
  /** 聚焦节点，渲染时放大并加描边 */
  focusNodeId?: string | null;
  /** 允许显示标签的节点；为空集合时全部显示 */
  labeledNodeIds?: Set<string>;
  className?: string;
}

export interface ForceGraphHandle {
  zoomIn: () => void;
  zoomOut: () => void;
  fitToScreen: () => void;
  center: () => void;
}
