/**
 * ForceGraph - 力导向图组件（基于 G6 v4）
 *
 * 创建时间: 2026-04-05
 * 创建者: GLM-5
 * 修改时间: 2026-04-06
 * 修改原因: react-force-graph-2d 的 _graphData 私有 API 在新版本不可用，
 *           后续重排逻辑失效。迁移至 G6 以获得原生布局控制能力。
 *
 * 任务: Phase 2-A 人物关系图谱
 * 说明: 基于 @antv/G6 v4 的力导向图，支持自定义渲染、多种布局、交互。
 *       G6 原生支持 preventOverlap 防重叠，无需额外后续重排逻辑。
 */
import { useRef, useEffect, useCallback, useImperativeHandle, useMemo, forwardRef, memo } from "react";
import { Graph } from "@antv/g6";
import type { INode, IG6GraphEvent } from "@antv/g6";
import { getCSSColorVar } from "@/lib/theme";
import type {
  GraphNode,
  GraphEdge,
  GraphNodeObject,
  ForceGraphProps,
  ForceGraphHandle,
} from "@/api/types";

/* ------------------------------------------------------------------ */
/*  Constants                                                         */
/* ------------------------------------------------------------------ */

const NODE_SIZE_MIN = 44;
const NODE_SIZE_MAX = 64;
const LINK_WIDTH_MIN = 1.5;
const LINK_WIDTH_MAX = 6;
const NODE_SPACING_MIN = 14;
const FIT_VIEW_PADDING = 24;
const INNER_RING_RATIO = 0.18;
const OUTER_RING_RATIO = 0.46;
const PERIPHERAL_RING_RATIO = 0.54;
const ISOLATED_RING_RATIO = 0.62;

interface EntityColors {
  character: string;
  group: string;
  organization: string;
  location: string;
  item: string;
  event: string;
  concept: string;
}

interface RelationColors {
  [key: string]: string;
}

interface AuxColors {
  background: string;
  text: string;
  neutral: string;
  positive: string;
  negative: string;
}

function getEntityColorsFromCSS(): EntityColors {
  return {
    character: getCSSColorVar("--primary"),
    group: getCSSColorVar("--chart-2"),
    organization: getCSSColorVar("--chart-3"),
    location: getCSSColorVar("--chart-4"),
    item: getCSSColorVar("--chart-5"),
    event: getCSSColorVar("--chart-neutral"),
    concept: getCSSColorVar("--chart-neutral"),
  };
}

function getRelationColorsFromCSS(): RelationColors {
  return {
    "友好": getCSSColorVar("--chart-positive"),
    "亲情": getCSSColorVar("--chart-positive"),
    "爱情": getCSSColorVar("--chart-positive"),
    "爱慕": getCSSColorVar("--chart-positive"),
    "敌对": getCSSColorVar("--chart-negative"),
    "仇恨": getCSSColorVar("--chart-negative"),
    "从属": getCSSColorVar("--chart-neutral"),
    "师徒": getCSSColorVar("--chart-neutral"),
    "家族": getCSSColorVar("--chart-neutral"),
  };
}

function getAuxColorsFromCSS(): AuxColors {
  return {
    background: getCSSColorVar("--background"),
    text: getCSSColorVar("--text"),
    neutral: getCSSColorVar("--chart-neutral"),
    positive: getCSSColorVar("--chart-positive"),
    negative: getCSSColorVar("--chart-negative"),
  };
}

function mapValue(value: number, inMin: number, inMax: number, outMin: number, outMax: number): number {
  if (inMax === inMin) return (outMin + outMax) / 2;
  return ((value - inMin) / (inMax - inMin)) * (outMax - outMin) + outMin;
}

/**
 * 调整颜色深浅（基于 HSL）
 * @param cssColor CSS 颜色值（hsl / hex / rgba）
 * @param depth 调整量：负数=加深（更暗），正数=变浅（更亮），范围 -1 ~ 1
 */
function adjustColorDepth(cssColor: string, depth: number): string {
  // 如果是 hsl() 格式，直接调整 lightness
  const hslMatch = cssColor.match(/hsl\(([\d.]+)\s+([\d.]+)%\s+([\d.]+)%\)/);
  if (hslMatch) {
    const h = parseFloat(hslMatch[1]);
    const s = parseFloat(hslMatch[2]);
    let l = parseFloat(hslMatch[3]);
    // 连续调整亮度：depth 范围 [-0.8, +0.5]，对应 lightness 变化 [-40%, +25%]
    l = Math.max(15, Math.min(75, l + depth * 50));
    return `hsl(${h} ${s}% ${l}%)`;
  }
  // 其他格式原样返回
  return cssColor;
}

/**
 * 将数值映射为归一化的深度因子 [0, 1]
 */
function normalizeToRange(value: number, minVal: number, maxVal: number): number {
  if (maxVal <= minVal) return 0.3;
  return Math.max(0, Math.min(1, (value - minVal) / (maxVal - minVal)));
}

function getConfiguredNodeSize(nodeCfg: unknown, fallback: number = NODE_SIZE_MIN): number {
  if (!nodeCfg || typeof nodeCfg !== "object") return fallback;
  const size = (nodeCfg as { size?: unknown }).size;
  return typeof size === "number" && Number.isFinite(size) ? size : fallback;
}

/* ------------------------------------------------------------------ */
/*  Main Component                                                    */
/* ------------------------------------------------------------------ */

export const ForceGraph = forwardRef<ForceGraphHandle, ForceGraphProps>(
  function ForceGraph(
    {
      data,
      onNodeClick,
      searchQuery,
      relationFilter,
      appearanceCountMap,
      className,
    },
    ref
  ) {
    const containerRef = useRef<HTMLDivElement>(null);
    const graphRef = useRef<Graph | null>(null);
    const entityColorsRef = useRef<EntityColors>(getEntityColorsFromCSS());
    const relationColorsRef = useRef<RelationColors>(getRelationColorsFromCSS());
    const auxColorsRef = useRef<AuxColors>(getAuxColorsFromCSS());

    // ---- 颜色工具函数 ----
    const getEntityColor = useCallback((entityType: string): string => {
      return (
        entityColorsRef.current[entityType as keyof EntityColors] ||
        auxColorsRef.current.neutral
      );
    }, []);

    const getRelationColor = useCallback((relationType: string): string => {
      return (
        relationColorsRef.current[relationType] ||
        auxColorsRef.current.text
      );
    }, []);

    // ---- 节点大小计算 ----
    const nodeDegrees = useMemo(() => {
      const degrees = new Map<string, number>();
      data.nodes.forEach((node) => degrees.set(node.entity_id, 0));
      data.edges.forEach((edge: GraphEdge) => {
        degrees.set(edge.source, (degrees.get(edge.source) || 0) + 1);
        degrees.set(edge.target, (degrees.get(edge.target) || 0) + 1);
      });
      return degrees;
    }, [data]);

    const degreeRange = useMemo(() => {
      const vals = Array.from(nodeDegrees.values());
      if (vals.length === 0) return { min: 0, max: 1 };
      return { min: Math.min(...vals), max: Math.max(...vals) };
    }, [nodeDegrees]);

    const weightRange = useMemo(() => {
      const weights = data.edges.map((e: GraphEdge) => e.weight ?? 1).filter((w): w is number => w !== undefined);
      if (weights.length === 0) return { min: 1, max: 1 };
      return { min: Math.min(...weights), max: Math.max(...weights) };
    }, [data.edges]);

    const getNodeSize = useCallback(
      (node: GraphNode): number => {
        if (appearanceCountMap && appearanceCountMap.size > 0) {
          let count = appearanceCountMap.get(node.entity_id);
          if (count === undefined) count = appearanceCountMap.get(node.name);
          const finalCount = count || 0;
          const counts = Array.from(appearanceCountMap.values()) as number[];
          if (counts.length === 0) return (NODE_SIZE_MIN + NODE_SIZE_MAX) / 2;
          const minC = Math.min(...counts), maxC = Math.max(...counts);
          if (maxC === minC) return (NODE_SIZE_MIN + NODE_SIZE_MAX) / 2;
          return mapValue(finalCount, minC, maxC, NODE_SIZE_MIN, NODE_SIZE_MAX);
        }
        const deg = nodeDegrees.get(node.entity_id) || 0;
        if (degreeRange.max === degreeRange.min) return (NODE_SIZE_MIN + NODE_SIZE_MAX) / 2;
        return mapValue(deg, degreeRange.min, degreeRange.max, NODE_SIZE_MIN, NODE_SIZE_MAX);
      },
      [nodeDegrees, degreeRange, appearanceCountMap]
    );

    // ---- 判断函数（仅保留搜索匹配，hover/选中由 G6 状态机管理）----
    const isSearchMatched = useCallback(
      (nodeName: string) =>
        searchQuery ? nodeName.toLowerCase().includes(searchQuery.toLowerCase()) : false,
      [searchQuery]
    );

    // ---- 过滤后的数据 ----
    // 内部使用 g6Data 格式（G6 用 edges 而非 links）
    const g6Data = useMemo(() => {
      // ForceGraphProps.data 实际传入的是带 links 字段的 ForceGraphData
      const rawData = data as unknown as Record<string, unknown>;
      const links = (rawData.links || rawData.edges || []) as Record<string, unknown>[];
      if (relationFilter.size === 0) {
        return {
          nodes: data.nodes.map(n => ({ ...n, id: n.entity_id })),
          edges: links,
        };
      }
      const filteredLinks = links.filter(
        (link: Record<string, unknown>) => !link.relation_type || relationFilter.has(String(link.relation_type))
      );
      const connectedIds = new Set<string>();
      filteredLinks.forEach((link: Record<string, unknown>) => {
        connectedIds.add(String(link.source));
        connectedIds.add(String(link.target));
      });
      const filteredNodes = data.nodes.filter((n: GraphNode) => connectedIds.has(n.entity_id)).map(n => ({ ...n, id: n.entity_id }));
      return { nodes: filteredNodes, edges: filteredLinks };
    }, [data, relationFilter]);

    const layoutDegrees = useMemo(() => {
      const degrees = new Map<string, number>();
      g6Data.nodes.forEach((node) => degrees.set(node.entity_id, 0));
      g6Data.edges.forEach((edge: Record<string, unknown>) => {
        const source = String(edge.source ?? "");
        const target = String(edge.target ?? "");
        if (degrees.has(source)) {
          degrees.set(source, (degrees.get(source) || 0) + 1);
        }
        if (degrees.has(target)) {
          degrees.set(target, (degrees.get(target) || 0) + 1);
        }
      });
      return degrees;
    }, [g6Data]);

    const orderedLayoutNodes = useMemo(() => {
      const nodes = [...g6Data.nodes];
      const connectedNodes = nodes
        .filter((node) => (layoutDegrees.get(node.entity_id) || 0) > 1)
        .sort((a, b) => {
          const degreeDiff = (layoutDegrees.get(b.entity_id) || 0) - (layoutDegrees.get(a.entity_id) || 0);
          if (degreeDiff !== 0) return degreeDiff;
          return a.name.localeCompare(b.name, "zh-CN");
        });
      const peripheralNodes = nodes
        .filter((node) => (layoutDegrees.get(node.entity_id) || 0) === 1)
        .sort((a, b) => a.name.localeCompare(b.name, "zh-CN"));
      const isolatedNodes = nodes
        .filter((node) => (layoutDegrees.get(node.entity_id) || 0) === 0)
        .sort((a, b) => a.name.localeCompare(b.name, "zh-CN"));

      return { connectedNodes, peripheralNodes, isolatedNodes };
    }, [g6Data.nodes, layoutDegrees]);

    // ---- 初始化 G6 实例 ----
    useEffect(() => {
      if (!containerRef.current) return;

      const container = containerRef.current;
      container.innerHTML = "";

      const width = container.clientWidth || 800;
      const height = container.clientHeight || 600;
      const nodeCount = Math.max(g6Data.nodes.length, 1);
      const densityScale = nodeCount >= 30 ? 1.25 : nodeCount >= 20 ? 1.1 : 1;
      const linkDistance = Math.round(165 * densityScale);
      const nodeStrength = Math.round(-210 * densityScale);
      const edgeStrength = nodeCount >= 30 ? 0.06 : 0.1;

      const graph = new Graph({
        container,
        width,
        height,
        fitView: true,
        fitViewPadding: FIT_VIEW_PADDING,
        modes: {
          default: ["drag-canvas", "zoom-canvas", "drag-node"],
        },
        layout: {
          type: "force",
          center: [width / 2, height / 2],
          preventOverlap: true,
          nodeSize: (node?: unknown) => getConfiguredNodeSize(node),
          collideStrength: 0.9,
          nodeSpacing: (node?: unknown) =>
            Math.max(NODE_SPACING_MIN, getConfiguredNodeSize(node) * 0.35),
          linkDistance,
          nodeStrength,
          edgeStrength,
          alphaDecay: 0.05,
          alphaMin: 0.002,
        },
        animate: true,
        // 节点状态样式（G6 原生状态机，不经过 React）
        nodeStateStyles: {
          active: {
            stroke: auxColorsRef.current.background,
            lineWidth: 2,
            shadowColor: "rgba(0,0,0,0.3)",
            shadowBlur: 10,
          },
          selected: {
            stroke: auxColorsRef.current.background,
            lineWidth: 3,
            shadowColor: "rgba(0,0,0,0.4)",
            shadowBlur: 12,
          },
        },
        defaultNode: {
          size: 48,
          style: {
            fill: "#94a3b8",
            stroke: "transparent",
            lineWidth: 2,
          },
        },
        defaultEdge: {
          style: {
            stroke: "#d1d5db",
            lineWidth: 1.5,
          },
        },
      });

      // 注册数据（G6 GraphData 格式：nodes + edges）
      // 使用均匀圆环分布作为初始位置，避免随机导致的重叠问题
      const cx = width / 2;
      const cy = height / 2;
      const shorterSide = Math.min(width, height);
      const coreNodeCount = orderedLayoutNodes.connectedNodes.length;
      const ringCount = Math.max(2, Math.ceil(Math.sqrt(Math.max(coreNodeCount, 1) / 2)));
      const nodesPerRing = Math.max(5, Math.ceil(Math.max(coreNodeCount, 1) / ringCount));
      const innerRadius = shorterSide * INNER_RING_RATIO;
      const maxRadius = shorterSide * OUTER_RING_RATIO;
      const ringStep = ringCount > 1 ? Math.max(42, (maxRadius - innerRadius) / (ringCount - 1)) : 0;
      const peripheralRadius = shorterSide * PERIPHERAL_RING_RATIO;
      const isolatedRadius = shorterSide * ISOLATED_RING_RATIO;

      const positionedNodes = new Map<string, GraphNode & { id: string; size: number; x: number; y: number }>();

      orderedLayoutNodes.connectedNodes.forEach((node, index) => {
        const ringIndex = Math.floor(index / nodesPerRing);
        const indexInRing = index % nodesPerRing;
        const nodesInCurrentRing = Math.max(1, Math.min(nodesPerRing, coreNodeCount - ringIndex * nodesPerRing));
        const angle = (2 * Math.PI * indexInRing) / nodesInCurrentRing + ringIndex * 0.45 + (Math.random() - 0.5) * 0.12;
        const baseRadius = Math.min(maxRadius, innerRadius + ringIndex * ringStep);
        const radius = Math.min(maxRadius, baseRadius + (Math.random() - 0.5) * 18);
        positionedNodes.set(node.entity_id, {
          ...node,
          id: node.entity_id,
          size: getNodeSize(node),
          x: cx + Math.cos(angle) * radius,
          y: cy + Math.sin(angle) * radius,
        });
      });

      orderedLayoutNodes.peripheralNodes.forEach((node, index) => {
        const count = Math.max(orderedLayoutNodes.peripheralNodes.length, 1);
        const angle = (2 * Math.PI * index) / count + Math.PI / 10 + (Math.random() - 0.5) * 0.08;
        const radius = peripheralRadius + (Math.random() - 0.5) * 14;
        positionedNodes.set(node.entity_id, {
          ...node,
          id: node.entity_id,
          size: getNodeSize(node),
          x: cx + Math.cos(angle) * radius,
          y: cy + Math.sin(angle) * radius,
        });
      });

      orderedLayoutNodes.isolatedNodes.forEach((node, index) => {
        const count = Math.max(orderedLayoutNodes.isolatedNodes.length, 1);
        const angle = (2 * Math.PI * index) / count - Math.PI / 6 + (Math.random() - 0.5) * 0.05;
        const radius = isolatedRadius + (Math.random() - 0.5) * 10;
        positionedNodes.set(node.entity_id, {
          ...node,
          id: node.entity_id,
          size: getNodeSize(node),
          x: cx + Math.cos(angle) * radius,
          y: cy + Math.sin(angle) * radius,
        });
      });

      graph.data({
        nodes: g6Data.nodes.map((node) => {
          const positionedNode = positionedNodes.get(node.entity_id);
          return (
            positionedNode ?? {
              ...node,
              id: node.entity_id,
              size: getNodeSize(node),
              x: cx,
              y: cy,
            }
          );
        }),
        edges: g6Data.edges as unknown as Record<string, unknown>[],
      });

      // 节点样式映射（G6 v4: 仅处理数据驱动的静态样式）
      // active/selected 状态由 G6 内部状态管理（nodeStateStyles），不在此处
      graph.node((nodeCfg: Record<string, unknown>) => {
        // 标签文字处理：超过 3 个字符时折行显示
        const rawName = String(nodeCfg.name || "");
        const name = rawName.length > 3 ? `${rawName.slice(0, 3)}\n${rawName.slice(3)}` : rawName;
        const entityType = String(nodeCfg.entity_type || "character");
        const baseColor = getEntityColor(entityType);
        const searched = isSearchMatched(name);

        let fill = baseColor;

        // ---- 颜色深浅：连续梯度（出现次数越多 → 越深，多色阶）----
        if (appearanceCountMap && appearanceCountMap.size > 0) {
          const entityId = String(nodeCfg.id || nodeCfg.entity_id || "");
          const count = appearanceCountMap.get(entityId) || appearanceCountMap.get(name) || 0;
          if (count > 1) {
            // 连续映射：count ∈ [1, max] → depthFactor ∈ [0.05, 0.7]
            const depthFactor = normalizeToRange(count, 1, Math.max(5, ...Array.from(appearanceCountMap.values()))) * 0.7 + 0.05;
            fill = adjustColorDepth(baseColor, -depthFactor);
          }
        } else {
          // 无出现次数数据时用度数
          const deg = nodeDegrees.get(String(nodeCfg.id || "")) || 0;
          if (deg >= degreeRange.max && degreeRange.max > degreeRange.min && deg > 1) {
            const depthFactor = normalizeToRange(deg, 1, degreeRange.max) * 0.6 + 0.05;
            fill = adjustColorDepth(baseColor, -depthFactor);
          }
        }
        // 节点最小 48px，确保能放下 3 个汉字
        const size = typeof nodeCfg.size === "number" ? Math.max(nodeCfg.size, 48) : 48;

        // 搜索匹配时高亮颜色
        if (searched && fill !== auxColorsRef.current.positive) {
          fill = auxColorsRef.current.positive;
        }

        // 字体大小：确保 3 个汉字能放进圆形节点（保守取值）
        const fontSize = Math.max(10, size * 0.30);

        return {
          size,
          style: {           // G6 v4：fill/stroke 必须在 style 内部才能覆盖 defaultNode
            fill,
            stroke: "transparent",
            lineWidth: 1.5,
          },
          label: name,
          labelCfg: {
            position: "center" as const,
            style: {
              fill: "#ffffff",
              fontSize,
              fontWeight: "bold" as const,
              shadowColor: "rgba(0,0,0,0.5)",
              shadowBlur: 3,
            },
          },
        };
      });

      // 边样式映射
      graph.edge((edgeCfg: Record<string, unknown>) => {
        const relType = String(edgeCfg.relation_type || "");
        const color = getRelationColor(relType);
        const width = typeof edgeCfg.weight === "number"
          ? mapValue(edgeCfg.weight, weightRange.min, weightRange.max, LINK_WIDTH_MIN, LINK_WIDTH_MAX)
          : (LINK_WIDTH_MIN + LINK_WIDTH_MAX) / 2;

        return {
          style: {           // G6 v4：stroke/lineWidth 必须在 style 内部
            stroke: color,
            lineWidth: width,
          },
          opacity: 0.7,
        };
      });

      // 事件绑定：点击节点
      graph.on("node:click", (evt: IG6GraphEvent) => {
        const targetItem = evt.item as unknown as INode | undefined;
        if (!targetItem) return;

        // 先清除之前选中的节点
        const selectedNodes = graph.findAllByState("node", "selected");
        selectedNodes.forEach((n) => graph.setItemState(n, "selected", false));

        // 设置新选中状态
        graph.setItemState(targetItem, "selected", true);

        // 通知父组件（仅用于显示详情面板）
        if (targetItem?.getModel) {
          const model = targetItem.getModel() as Record<string, unknown>;
          onNodeClick(model as unknown as GraphNodeObject);
        }
      });

      // 事件绑定：鼠标进入节点（用 G6 内部状态管理高亮，不触发 React 重渲染）
      graph.on("node:mouseenter", (evt: IG6GraphEvent) => {
        const targetItem = evt.item as unknown as INode | undefined;
        if (!targetItem) return;
        graph.setItemState(targetItem, "active", true);

        // 高亮关联的边
        const edges = targetItem.getEdges();
        edges.forEach((edge) => {
          graph.setItemState(edge, "active", true);
        });
        // 不调用 onNodeHover —— 完全避免触发父组件状态更新和重渲染链
      });

      // 事件绑定：鼠标离开节点（仅清除 G6 内部状态，不通知父组件）
      graph.on("node:mouseleave", () => {
        // 清除所有 active 状态
        const activeNodes = graph.findAllByState("node", "active");
        activeNodes.forEach((n) => graph.setItemState(n, "active", false));
        const activeEdges = graph.findAllByState("edge", "active");
        activeEdges.forEach((e) => graph.setItemState(e, "active", false));
        // 不调用 onNodeHover(null) —— 避免触发父组件 setHighlightedNodes 导致重渲染链
      });

      // 渲染
      graph.render();

      // 窗口 resize
      const observer = new ResizeObserver(() => {
        const w = container.clientWidth;
        const h = container.clientHeight;
        if (w > 0 && h > 0) graph.changeSize(w, h);
      });
      observer.observe(container);

      graphRef.current = graph;

      return () => {
        observer.disconnect();
        graph.destroy();
        graphRef.current = null;
      };
    }, [
      appearanceCountMap,
      degreeRange,
      g6Data,
      getEntityColor,
      getNodeSize,
      getRelationColor,
      isSearchMatched,
      nodeDegrees,
      onNodeClick,
      orderedLayoutNodes,
      weightRange,
    ]);

    // ---- imperative handle ----
    useImperativeHandle(ref, () => ({
      zoomIn: () => { graphRef.current?.zoom(1.3, undefined); },
      zoomOut: () => { graphRef.current?.zoom(0.77, undefined); },
      fitToScreen: () => { graphRef.current?.fitView(300); },
      center: () => { graphRef.current?.fitCenter(); },
    }), []);

    return <div ref={containerRef} className={className} style={{ width: "100%", height: "100%" }} />;
  }
);

ForceGraph.displayName = "ForceGraph";

export default memo(ForceGraph);
