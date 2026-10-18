/**
 * ForceGraph - 力导向图组件（基于 G6 v4）
 *
 * 支持自定义渲染、多种布局与交互；G6 原生 preventOverlap 防重叠，
 * 数据适配、布局、调色与 G6 生命周期分别抽到独立模块，本组件只保留编排层职责
 */
import { forwardRef, memo, useImperativeHandle, useMemo, useRef } from "react";
import type { Graph } from "@antv/g6";

import type { ForceGraphHandle, ForceGraphProps } from "./forceGraphTypes";
import { buildForceGraphModel } from "./forceGraph/forceGraphDataAdapter";
import { createForceGraphPalette } from "./forceGraph/forceGraphPalette";
import { useG6ForceGraph } from "./forceGraph/useG6ForceGraph";

export const ForceGraph = forwardRef<ForceGraphHandle, ForceGraphProps>(function ForceGraph(
  { data, onNodeClick, searchQuery, relationFilter, appearanceCountMap, className },
  ref
) {
  const containerRef = useRef<HTMLDivElement>(null);
  const graphRef = useRef<Graph | null>(null);

  const palette = useMemo(() => createForceGraphPalette(), []);
  const model = useMemo(
    () =>
      buildForceGraphModel({
        data,
        relationFilter,
        appearanceCountMap,
      }),
    [appearanceCountMap, data, relationFilter]
  );

  useG6ForceGraph({
    containerRef,
    model,
    palette,
    searchQuery,
    appearanceCountMap,
    onNodeClick,
    onGraphReady: (graph) => {
      graphRef.current = graph;
    },
  });

  useImperativeHandle(
    ref,
    () => ({
      zoomIn: () => {
        graphRef.current?.zoom(1.3, undefined);
      },
      zoomOut: () => {
        graphRef.current?.zoom(0.77, undefined);
      },
      fitToScreen: () => {
        graphRef.current?.fitView(300);
      },
      center: () => {
        graphRef.current?.fitCenter();
      },
    }),
    []
  );

  return <div ref={containerRef} className={className} style={{ width: "100%", height: "100%" }} />;
});

ForceGraph.displayName = "ForceGraph";

export default memo(ForceGraph);
