import { useRef, useMemo, useCallback, useEffect, useImperativeHandle, forwardRef } from "react";
import ForceGraph2D, { type ForceGraphMethods } from "react-force-graph-2d";
import type {
  GraphData,
  GraphNode,
  GraphEdge,
  GraphNodeObject,
  GraphLinkObject,
  ForceGraphData,
} from "@/api/types";

/* ------------------------------------------------------------------ */
/*  Types                                                             */
/* ------------------------------------------------------------------ */

export interface ForceGraphProps {
  data: GraphData;
  selectedNode: GraphNode | null;
  onNodeClick: (node: GraphNode) => void;
  onNodeHover: (node: GraphNode | null) => void;
  highlightedNodes: Set<string>;
  searchQuery: string;
  relationFilter: Set<string>;
  className?: string;
}

/**
 * ForceGraph 暴露给父组件的方法
 */
export interface ForceGraphHandle {
  zoomIn: () => void;
  zoomOut: () => void;
  fitToScreen: () => void;
  center: () => void;
}

/* ------------------------------------------------------------------ */
/*  Constants - Canvas 不支持 CSS 变量，需使用实际颜色值              */
/* ------------------------------------------------------------------ */

const ENTITY_TYPE_COLORS: Record<string, string> = {
  character: "hsl(234, 89%, 55%)",
  group: "hsl(274, 79%, 55%)",
  organization: "hsl(194, 79%, 55%)",
  location: "hsl(314, 74%, 55%)",
  item: "hsl(154, 74%, 55%)",
  event: "hsl(234, 10%, 60%)",
  concept: "hsl(234, 10%, 40%)",
};

const RELATION_TYPE_COLORS: Record<string, string> = {
  友好: "hsl(145, 55%, 48%)",
  敌对: "hsl(0, 65%, 55%)",
  从属: "hsl(234, 10%, 60%)",
  合作: "hsl(274, 79%, 55%)",
  亲情: "hsl(194, 79%, 55%)",
  爱情: "hsl(314, 74%, 55%)",
  师徒: "hsl(154, 74%, 55%)",
};

/**
 * 层级关系类型：这些类型的边使用虚线样式
 * 设计文档 §2.5 要求："层级关系用虚线，动态关系用实线"
 * 如果后端数据中包含 is_hierarchical 字段，优先使用该字段；
 * 否则根据关系类型名称判断（从属、师徒、合作 等属于层级关系）
 */
const HIERARCHICAL_RELATION_TYPES = new Set([
  "从属",
  "师徒",
  "上下级",
  "隶属",
  "管理",
]);

const NODE_SIZE_MIN = 8;
const NODE_SIZE_MAX = 40;
const LINK_WIDTH_MIN = 1;
const LINK_WIDTH_MAX = 4;
const LABEL_DEGREE_THRESHOLD = 3;

/* ------------------------------------------------------------------ */
/*  Helper Functions                                                  */
/* ------------------------------------------------------------------ */

function getEntityColor(entityType: string): string {
  return ENTITY_TYPE_COLORS[entityType] || "hsl(234, 10%, 60%)";
}

function getRelationColor(relationType: string): string {
  return RELATION_TYPE_COLORS[relationType] || "hsl(234, 10%, 60%)";
}

/**
 * 判断是否为层级关系（应使用虚线）
 */
function isHierarchicalRelation(relationType: string): boolean {
  if (!relationType) return false;
  return HIERARCHICAL_RELATION_TYPES.has(relationType);
}

function mapValue(
  value: number,
  inMin: number,
  inMax: number,
  outMin: number,
  outMax: number
): number {
  const clampedValue = Math.max(inMin, Math.min(inMax, value));
  const ratio = (clampedValue - inMin) / (inMax - inMin);
  return outMin + ratio * (outMax - outMin);
}

/* ------------------------------------------------------------------ */
/*  Main Component                                                    */
/* ------------------------------------------------------------------ */

/**
 * 力导向图组件 - 展示知识图谱节点和关系
 *
 * 创建时间: 2026-04-05
 * 创建者: GLM-5
 * 任务: 创建 ForceGraph 组件
 * 说明: 使用 react-force-graph-2d 实现力导向图，支持节点大小/颜色映射、
 *       边粗细/颜色映射、虚线样式区分层级关系、悬浮高亮、点击事件、拖拽布局、缩放平移等功能
 *
 * 修改时间: 2026-04-05
 * 修改者: Code Review Fix
 * 修改内容:
 *   - 改为 forwardRef + useImperativeHandle，暴露 zoomIn/zoomOut/fitToScreen/center 方法
 *   - 添加边虚线样式支持（层级关系使用虚线，动态关系使用实线）
 *   - 新增 HIERARCHICAL_RELATION_TYPES 配置
 */
export const ForceGraph = forwardRef<ForceGraphHandle, ForceGraphProps>(
  function ForceGraph({
    data,
    selectedNode,
    onNodeClick,
    onNodeHover,
    highlightedNodes,
    searchQuery,
    relationFilter,
    className,
  }, ref) {
  const graphRef = useRef<ForceGraphMethods<GraphNodeObject, GraphLinkObject> | undefined>(undefined);

  // 通过 useImperativeHandle 暴露方法给父组件
  useImperativeHandle(ref, () => ({
    zoomIn: () => {
      const fg = graphRef.current;
      if (!fg) return;
      const zoom = fg.zoom();
      fg.zoom(zoom * 1.3, 400);
    },
    zoomOut: () => {
      const fg = graphRef.current;
      if (!fg) return;
      const zoom = fg.zoom();
      fg.zoom(zoom / 1.3, 400);
    },
    fitToScreen: () => {
      graphRef.current?.zoomToFit(400, 50);
    },
    center: () => {
      graphRef.current?.centerAt(0, 0, 400);
    },
  }), []);

  const graphDataWithLinks = useMemo((): ForceGraphData => {
    return {
      ...data,
      links: (data.edges || []) as GraphLinkObject[],
    };
  }, [data]);

  const nodeDegrees = useMemo(() => {
    const degrees = new Map<string, number>();
    data.nodes.forEach((node) => {
      degrees.set(node.entity_id, 0);
    });
    data.edges.forEach((edge) => {
      const sourceId = edge.source;
      const targetId = edge.target;
      degrees.set(sourceId, (degrees.get(sourceId) || 0) + 1);
      degrees.set(targetId, (degrees.get(targetId) || 0) + 1);
    });
    return degrees;
  }, [data]);

  const degreeRange = useMemo(() => {
    const degrees = Array.from(nodeDegrees.values());
    if (degrees.length === 0) return { min: 0, max: 1 };
    return {
      min: Math.min(...degrees),
      max: Math.max(...degrees),
    };
  }, [nodeDegrees]);

  const weightRange = useMemo(() => {
    const weights = data.edges
      .map((edge) => edge.weight ?? 1)
      .filter((w): w is number => w !== undefined);
    if (weights.length === 0) return { min: 1, max: 1 };
    return {
      min: Math.min(...weights),
      max: Math.max(...weights),
    };
  }, [data.edges]);

  // 关系类型过滤：只显示选中的关系类型对应的边和连接的节点
  const filteredData = useMemo((): ForceGraphData => {
    if (relationFilter.size === 0) {
      return graphDataWithLinks;
    }
    const filteredEdges = data.edges.filter((edge) => {
      const relationType = edge.relation_type;
      if (!relationType) return true;
      return relationFilter.has(relationType);
    });
    const connectedNodeIds = new Set<string>();
    filteredEdges.forEach((edge) => {
      connectedNodeIds.add(edge.source);
      connectedNodeIds.add(edge.target);
    });
    const filteredNodes = data.nodes.filter((node) =>
      connectedNodeIds.has(node.entity_id)
    );
    return {
      nodes: filteredNodes as GraphNodeObject[],
      links: filteredEdges as GraphLinkObject[],
    };
  }, [data, graphDataWithLinks, relationFilter]);

  // 搜索匹配的节点 ID 集合
  const searchMatchedNodes = useMemo(() => {
    if (!searchQuery.trim()) return new Set<string>();
    const query = searchQuery.toLowerCase();
    const matched = new Set<string>();
    data.nodes.forEach((node) => {
      if (node.name.toLowerCase().includes(query)) {
        matched.add(node.entity_id);
      }
    });
    return matched;
  }, [data.nodes, searchQuery]);

  /* ---- 节点/边的尺寸/状态计算回调 ---- */

  const getNodeSize = useCallback(
    (node: GraphNode): number => {
      const degree = nodeDegrees.get(node.entity_id) || 0;
      if (degreeRange.max === degreeRange.min) {
        return (NODE_SIZE_MIN + NODE_SIZE_MAX) / 2;
      }
      return mapValue(
        degree,
        degreeRange.min,
        degreeRange.max,
        NODE_SIZE_MIN,
        NODE_SIZE_MAX
      );
    },
    [nodeDegrees, degreeRange]
  );

  const getLinkWidth = useCallback(
    (link: GraphEdge): number => {
      const weight = link.weight ?? 1;
      if (weightRange.max === weightRange.min) {
        return (LINK_WIDTH_MIN + LINK_WIDTH_MAX) / 2;
      }
      return mapValue(
        weight,
        weightRange.min,
        weightRange.max,
        LINK_WIDTH_MIN,
        LINK_WIDTH_MAX
      );
    },
    [weightRange]
  );

  const isNodeHighlighted = useCallback(
    (node: GraphNode): boolean => {
      return highlightedNodes.has(node.entity_id);
    },
    [highlightedNodes]
  );

  const isNodeSelected = useCallback(
    (node: GraphNode): boolean => {
      return selectedNode?.entity_id === node.entity_id;
    },
    [selectedNode]
  );

  const isNodeSearchMatched = useCallback(
    (node: GraphNode): boolean => {
      return searchMatchedNodes.has(node.entity_id);
    },
    [searchMatchedNodes]
  );

  const shouldShowLabel = useCallback(
    (node: GraphNode): boolean => {
      const degree = nodeDegrees.get(node.entity_id) || 0;
      return degree >= LABEL_DEGREE_THRESHOLD;
    },
    [nodeDegrees]
  );

  /* ---- Canvas 渲染函数 ---- */

  const paintNode = useCallback(
    (node: GraphNodeObject, ctx: CanvasRenderingContext2D, globalScale: number) => {
      const size = getNodeSize(node);
      const isHighlighted = isNodeHighlighted(node);
      const isSelected = isNodeSelected(node);
      const isSearchMatched = isNodeSearchMatched(node);
      const showLabel = shouldShowLabel(node);

      const baseColor = getEntityColor(node.entity_type);
      let nodeColor = baseColor;
      let opacity = 1;

      // 高亮模式：未高亮的节点变暗
      if (highlightedNodes.size > 0 && !isHighlighted) {
        opacity = 0.2;
      }

      // 搜索匹配：高亮显示为绿色
      if (searchQuery && isSearchMatched) {
        nodeColor = "hsl(145, 55%, 48%)";
        opacity = 1;
      }

      ctx.globalAlpha = opacity;

      // 绘制节点圆形
      ctx.beginPath();
      ctx.arc(node.x || 0, node.y || 0, size, 0, 2 * Math.PI);
      ctx.fillStyle = nodeColor;
      ctx.fill();

      // 选中态白色边框
      if (isSelected) {
        ctx.strokeStyle = "hsl(0, 0%, 100%)";
        ctx.lineWidth = 3;
        ctx.stroke();
      }

      // 高亮态白色边框（非选中时较细）
      if (isHighlighted && !isSelected) {
        ctx.strokeStyle = "hsl(0, 0%, 100%)";
        ctx.lineWidth = 2;
        ctx.stroke();
      }

      ctx.globalAlpha = 1;

      // 标签绘制（度数 >= 阈值 或 处于高亮/搜索匹配状态时显示）
      if (showLabel || isHighlighted || isSearchMatched) {
        const label = node.name;
        const fontSize = Math.max(10, 12 / globalScale);
        ctx.font = `${fontSize}px Sans-Serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "top";
        ctx.fillStyle = "hsl(234, 15%, 12%)";
        ctx.fillText(label, node.x || 0, (node.y || 0) + size + 2);
      }
    },
    [
      getNodeSize,
      isNodeHighlighted,
      isNodeSelected,
      isNodeSearchMatched,
      shouldShowLabel,
      highlightedNodes.size,
      searchQuery,
    ]
  );

  /**
   * 绘制连线
   * - 层级关系（从属、师徒等）使用虚线
   * - 动态关系（友好、敌对等）使用实线
   */
  const paintLink = useCallback(
    (link: GraphLinkObject, ctx: CanvasRenderingContext2D) => {
      const source = typeof link.source === "string" ? null : link.source;
      const target = typeof link.target === "string" ? null : link.target;

      if (!source || !target || !source.x || !source.y || !target.x || !target.y) return;

      const width = getLinkWidth(link as GraphEdge);
      const color = getRelationColor(link.relation_type || "");

      const isSourceHighlighted = highlightedNodes.has(source.entity_id);
      const isTargetHighlighted = highlightedNodes.has(target.entity_id);
      const isLinkHighlighted = isSourceHighlighted && isTargetHighlighted;

      let opacity = 0.6;
      if (highlightedNodes.size > 0 && !isLinkHighlighted) {
        opacity = 0.1;
      }

      ctx.globalAlpha = opacity;
      ctx.beginPath();
      ctx.moveTo(source.x, source.y);

      // 判断是否需要虚线样式
      const useDashedLine = isHierarchicalRelation(link.relation_type || "");

      if (useDashedLine) {
        // 虚线样式：层级关系 [6, 4] 间隔
        ctx.setLineDash([6, 4]);
      } else {
        // 实线样式：动态关系
        ctx.setLineDash([]);
      }

      ctx.lineTo(target.x, target.y);
      ctx.strokeStyle = color;
      ctx.lineWidth = width;
      ctx.stroke();

      // 重置虚线设置（防止影响后续绘制）
      ctx.setLineDash([]);
      ctx.globalAlpha = 1;
    },
    [getLinkWidth, highlightedNodes]
  );

  /* ---- 交互事件处理 ---- */

  const handleNodeClick = useCallback(
    (node: GraphNodeObject) => {
      onNodeClick(node);
    },
    [onNodeClick]
  );

  const handleNodeHover = useCallback(
    (node: GraphNodeObject | null) => {
      onNodeHover(node);
      document.body.style.cursor = node ? "pointer" : "default";
    },
    [onNodeHover]
  );

  /* ---- 力学模拟参数配置 ---- */

  useEffect(() => {
    if (graphRef.current) {
      const fg = graphRef.current;
      fg.d3Force("charge")?.strength(-200);
      fg.d3Force("link")?.distance(80);
    }
  }, []);

  /* ---- 渲染 ---- */

  return (
    <div className={className}>
      <ForceGraph2D
        ref={graphRef}
        graphData={filteredData}
        nodeId="entity_id"
        linkSource="source"
        linkTarget="target"
        nodeCanvasObject={paintNode}
        linkCanvasObject={paintLink}
        onNodeClick={handleNodeClick}
        onNodeHover={handleNodeHover}
        nodeRelSize={1}
        linkDirectionalParticles={0}
        linkDirectionalArrowLength={0}
        enableNodeDrag={true}
        enableZoomInteraction={true}
        enablePanInteraction={true}
        minZoom={0.1}
        maxZoom={4}
        warmupTicks={100}
        cooldownTicks={100}
        cooldownTime={1500}
      />
    </div>
  );
  }
);

ForceGraph.displayName = "ForceGraph";

export default ForceGraph;
