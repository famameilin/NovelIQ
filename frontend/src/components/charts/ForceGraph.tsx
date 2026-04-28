/**
 * ForceGraph - 力导向图组件（基于 G6 v4）
 *
 * 修改原因: react-force-graph-2d 的 _graphData 私有 API 在新版本不可用，
 *           后续重排逻辑失效。迁移至 G6 以获得原生布局控制能力
 *
 * 基于 @antv/G6 v4 的力导向图，支持自定义渲染、多种布局、交互
 *       G6 原生支持 preventOverlap 防重叠，无需额外后续重排逻辑
 *
 *   - 拆分数据适配、布局、调色和 G6 生命周期 hook
 *   - 让 ForceGraph 只保留编排层职责，减少单文件复杂度
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
