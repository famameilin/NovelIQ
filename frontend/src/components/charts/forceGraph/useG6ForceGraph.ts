import { useEffect } from "react";
import type { RefObject } from "react";
import { Graph } from "@antv/g6";
import type { IG6GraphEvent, INode } from "@antv/g6";

import type { GraphNodeObject } from "@/components/charts/forceGraphTypes";

import {
  getConfiguredNodeSize,
  LINK_WIDTH_MAX,
  LINK_WIDTH_MIN,
  mapValue,
  normalizeToRange,
  type ForceGraphModel,
} from "./forceGraphDataAdapter";
import {
  buildForceLayoutConfig,
  buildInitialGraphPayload,
  FIT_VIEW_PADDING,
  NODE_SPACING_MIN,
} from "./forceGraphLayout";
import type { ForceGraphPalette } from "./forceGraphPalette";

interface UseG6ForceGraphOptions {
  containerRef: RefObject<HTMLDivElement | null>;
  model: ForceGraphModel;
  palette: ForceGraphPalette;
  searchQuery: string;
  appearanceCountMap?: Map<string, number>;
  onNodeClick: (node: GraphNodeObject) => void;
  onGraphReady: (graph: Graph | null) => void;
}

// 2026-04-23，任务：复杂度与耦合审查 P1
// 新建原因：把 G6 实例初始化、事件绑定和销毁都封到独立 hook，减少 ForceGraph 组件的生命周期负担。
export function useG6ForceGraph({
  containerRef,
  model,
  palette,
  searchQuery,
  appearanceCountMap,
  onNodeClick,
  onGraphReady,
}: UseG6ForceGraphOptions) {
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    container.innerHTML = "";
    const width = container.clientWidth || 800;
    const height = container.clientHeight || 600;
    const nodeCount = Math.max(model.g6Data.nodes.length, 1);
    const layoutConfig = buildForceLayoutConfig(width, height, nodeCount);

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
        ...layoutConfig,
        nodeSize: (node?: unknown) => getConfiguredNodeSize(node),
        nodeSpacing: (node?: unknown) => Math.max(NODE_SPACING_MIN, getConfiguredNodeSize(node) * 0.35),
      },
      animate: true,
      nodeStateStyles: {
        active: {
          stroke: palette.auxColors.background,
          lineWidth: 2,
          shadowColor: "rgba(0,0,0,0.3)",
          shadowBlur: 10,
        },
        selected: {
          stroke: palette.auxColors.background,
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

    const graphDataPayload = buildInitialGraphPayload(model, width, height);
    graph.data(graphDataPayload as unknown as Parameters<typeof graph.data>[0]);

    const isSearchMatched = (nodeName: string) =>
      searchQuery ? nodeName.toLowerCase().includes(searchQuery.toLowerCase()) : false;

    graph.node((nodeCfg: Record<string, unknown>) => {
      const rawName = String(nodeCfg.name || "");
      const wrappedName = rawName.length > 3 ? `${rawName.slice(0, 3)}\n${rawName.slice(3)}` : rawName;
      const entityType = String(nodeCfg.entity_type || "character");
      const baseColor = palette.entityColors[entityType as keyof typeof palette.entityColors] || palette.auxColors.neutral;
      const searched = isSearchMatched(rawName);

      let fill = baseColor;
      if (appearanceCountMap && appearanceCountMap.size > 0) {
        const entityId = String(nodeCfg.id || nodeCfg.entity_id || "");
        const count = appearanceCountMap.get(entityId) || appearanceCountMap.get(rawName) || 0;
        if (count > 1) {
          const maxCount = Math.max(5, ...Array.from(appearanceCountMap.values()));
          const depthFactor = normalizeToRange(count, 1, maxCount) * 0.7 + 0.05;
          fill = adjustColorDepth(baseColor, -depthFactor);
        }
      } else {
        const degree = model.nodeDegrees.get(String(nodeCfg.id || "")) || 0;
        if (degree >= model.degreeRange.max && model.degreeRange.max > model.degreeRange.min && degree > 1) {
          const depthFactor = normalizeToRange(degree, 1, model.degreeRange.max) * 0.6 + 0.05;
          fill = adjustColorDepth(baseColor, -depthFactor);
        }
      }

      const size = typeof nodeCfg.size === "number" ? Math.max(nodeCfg.size, 48) : 48;
      if (searched && fill !== palette.auxColors.positive) {
        fill = palette.auxColors.positive;
      }
      const fontSize = Math.max(10, size * 0.3);

      return {
        size,
        style: {
          fill,
          stroke: "transparent",
          lineWidth: 1.5,
        },
        label: wrappedName,
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

    graph.edge((edgeCfg: Record<string, unknown>) => {
      const relationType = String(edgeCfg.relation_type || "");
      const color = palette.relationColors[relationType] || palette.auxColors.text;
      const width =
        typeof edgeCfg.weight === "number"
          ? mapValue(edgeCfg.weight, model.weightRange.min, model.weightRange.max, LINK_WIDTH_MIN, LINK_WIDTH_MAX)
          : (LINK_WIDTH_MIN + LINK_WIDTH_MAX) / 2;

      return {
        style: {
          stroke: color,
          lineWidth: width,
        },
        opacity: 0.7,
      };
    });

    graph.on("node:click", (evt: IG6GraphEvent) => {
      const targetItem = evt.item as unknown as INode | undefined;
      if (!targetItem) return;

      const selectedNodes = graph.findAllByState("node", "selected");
      selectedNodes.forEach((node) => graph.setItemState(node, "selected", false));
      graph.setItemState(targetItem, "selected", true);

      if (targetItem.getModel) {
        const graphModel = targetItem.getModel() as unknown as GraphNodeObject;
        onNodeClick(graphModel);
      }
    });

    graph.on("node:mouseenter", (evt: IG6GraphEvent) => {
      const targetItem = evt.item as unknown as INode | undefined;
      if (!targetItem) return;
      graph.setItemState(targetItem, "active", true);
      targetItem.getEdges().forEach((edge) => {
        graph.setItemState(edge, "active", true);
      });
    });

    graph.on("node:mouseleave", () => {
      graph.findAllByState("node", "active").forEach((node) => graph.setItemState(node, "active", false));
      graph.findAllByState("edge", "active").forEach((edge) => graph.setItemState(edge, "active", false));
    });

    graph.render();

    const observer = new ResizeObserver(() => {
      const nextWidth = container.clientWidth;
      const nextHeight = container.clientHeight;
      if (nextWidth > 0 && nextHeight > 0) {
        graph.changeSize(nextWidth, nextHeight);
      }
    });
    observer.observe(container);
    onGraphReady(graph);

    return () => {
      observer.disconnect();
      graph.destroy();
      onGraphReady(null);
    };
  }, [appearanceCountMap, containerRef, model, onGraphReady, onNodeClick, palette, searchQuery]);
}

function adjustColorDepth(cssColor: string, depth: number): string {
  const hslMatch = cssColor.match(/hsl\(([\d.]+)\s+([\d.]+)%\s+([\d.]+)%\)/);
  if (!hslMatch) {
    return cssColor;
  }

  const hue = parseFloat(hslMatch[1]);
  const saturation = parseFloat(hslMatch[2]);
  let lightness = parseFloat(hslMatch[3]);
  lightness = Math.max(15, Math.min(75, lightness + depth * 50));
  return `hsl(${hue} ${saturation}% ${lightness}%)`;
}
