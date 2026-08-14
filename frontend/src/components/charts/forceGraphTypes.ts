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
  className?: string;
}

export interface ForceGraphHandle {
  zoomIn: () => void;
  zoomOut: () => void;
  fitToScreen: () => void;
  center: () => void;
}
