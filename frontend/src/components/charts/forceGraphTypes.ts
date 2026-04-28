// ForceGraph 的 G6 运行时类型归属于图谱组件边界，避免污染后端 API contract 类型。

import type {
  GraphData,
  GraphEvent,
  GraphEventsPageInfo,
  GraphNode,
  GraphPageQualityReport,
  GraphPageSummary,
} from "@/api/types";

export interface GraphNodeObject extends GraphNode {
  x?: number;
  y?: number;
  vx?: number;
  vy?: number;
}

export interface GraphLinkObject {
  source: string | GraphNodeObject;
  target: string | GraphNodeObject;
  relation_type?: string;
  weight?: number;
}

export interface ForceGraphData {
  nodes: GraphNodeObject[];
  links: GraphLinkObject[];
  events: GraphEvent[];
  events_page: GraphEventsPageInfo;
  summary: GraphPageSummary;
  quality: GraphPageQualityReport;
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
