/**
 * GraphPage - 人物关系图谱页面
 *
 * 创建时间: 2026-04-05
 * 创建者: GLM-5
 * 任务: Phase 2-A 人物关系图谱页面实现
 * 说明: 展示人物关系力导向图，支持缩放、居中、关系类型过滤、节点搜索和详情面板
 */
import { useEffect, useState, useCallback, useMemo, useRef } from "react";
import { useParams, useSearchParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import ForceGraph2D, { type ForceGraphMethods } from "react-force-graph-2d";
import { getGraph } from "@/api/results";
import { getNovel } from "@/api/novels";
import { useNovelStore } from "@/store/novelStore";
import { PageContainer } from "@/components/layout/PageContainer";
import { NovelHeader } from "@/components/common/NovelHeader";
import { GraphToolbar } from "@/components/charts/GraphToolbar";
import { NodeDetailPanel, type RelatedNodeInfo } from "@/components/charts/NodeDetailPanel";
import { GraphLegend } from "@/components/charts/GraphLegend";
import { Button } from "@/components/ui/button";
import { RefreshCw } from "lucide-react";
import type {
  GraphNode,
  GraphData,
  GraphNodeObject,
  GraphLinkObject,
  ForceGraphData,
} from "@/api/types";

/* ------------------------------------------------------------------ */
/*  Constants                                                         */
/* ------------------------------------------------------------------ */

const STALE_TIME = 5 * 60 * 1000;

/* ------------------------------------------------------------------ */
/*  Main Component                                                    */
/* ------------------------------------------------------------------ */

export function GraphPage() {
  const { novelId } = useParams<{ novelId: string }>();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { currentTaskId, setNovel, setTask } = useNovelStore();

  const urlTaskId = searchParams.get("task_id");

  const graphRef = useRef<ForceGraphMethods<GraphNodeObject, GraphLinkObject> | undefined>(undefined);

  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [highlightedNodes, setHighlightedNodes] = useState<Set<string>>(new Set());
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedRelationTypes, setSelectedRelationTypes] = useState<Set<string>>(new Set());
  const [isPanelOpen, setIsPanelOpen] = useState(false);

  useEffect(() => {
    if (novelId) {
      setNovel(novelId);
      if (urlTaskId) {
        setTask(urlTaskId);
      }
    }
  }, [novelId, urlTaskId, setNovel, setTask]);

  useEffect(() => {
    if (currentTaskId && searchParams.get("task_id") !== currentTaskId) {
      navigate(`/novels/${novelId}/graph?task_id=${currentTaskId}`, { replace: true });
    }
  }, [currentTaskId, novelId, navigate, searchParams]);

  const enabled = !!novelId && !!currentTaskId;

  const graphQuery = useQuery({
    queryKey: ["graph", novelId, currentTaskId],
    queryFn: () => getGraph(novelId!, currentTaskId!),
    enabled,
    staleTime: STALE_TIME,
  });

  const novelQuery = useQuery({
    queryKey: ["novel", novelId],
    queryFn: () => getNovel(novelId!),
    enabled: !!novelId,
    staleTime: STALE_TIME,
  });

  const novelTitle = novelQuery.data?.title ?? "小说详情";

  const graphData = graphQuery.data;

  const forceGraphData = useMemo((): ForceGraphData | undefined => {
    if (!graphData) return undefined;
    return {
      ...graphData,
      links: (graphData.edges || []) as GraphLinkObject[],
    };
  }, [graphData]);

  const relationTypes = useMemo(() => {
    if (!graphData?.edges) return [];
    const types = new Set<string>();
    graphData.edges.forEach((edge) => {
      if (edge.relation_type) {
        types.add(edge.relation_type);
      }
    });
    return Array.from(types);
  }, [graphData]);

  const relatedNodes = useMemo((): RelatedNodeInfo[] => {
    if (!selectedNode || !graphData) return [];

    const related: RelatedNodeInfo[] = [];
    const nodeMap = new Map<string, GraphNode>();
    graphData.nodes.forEach((node) => {
      nodeMap.set(node.entity_id, node);
    });

    graphData.edges.forEach((edge) => {
      if (edge.source === selectedNode.entity_id) {
        const targetNode = nodeMap.get(edge.target);
        if (targetNode) {
          related.push({
            node: targetNode,
            relationType: edge.relation_type || "未知",
            weight: edge.weight ?? 1,
          });
        }
      } else if (edge.target === selectedNode.entity_id) {
        const sourceNode = nodeMap.get(edge.source);
        if (sourceNode) {
          related.push({
            node: sourceNode,
            relationType: edge.relation_type || "未知",
            weight: edge.weight ?? 1,
          });
        }
      }
    });

    return related;
  }, [selectedNode, graphData]);

  const handleZoomIn = useCallback(() => {
    const fg = graphRef.current;
    if (!fg) return;
    const zoom = fg.zoom();
    fg.zoom(zoom * 1.3, 400);
  }, []);

  const handleZoomOut = useCallback(() => {
    const fg = graphRef.current;
    if (!fg) return;
    const zoom = fg.zoom();
    fg.zoom(zoom / 1.3, 400);
  }, []);

  const handleFitToScreen = useCallback(() => {
    const fg = graphRef.current;
    if (!fg) return;
    fg.zoomToFit(400, 50);
  }, []);

  const handleCenter = useCallback(() => {
    const fg = graphRef.current;
    if (!fg) return;
    fg.centerAt(0, 0, 400);
  }, []);

  const handleRelationTypeChange = useCallback((types: Set<string>) => {
    setSelectedRelationTypes(types);
  }, []);

  const handleSearchChange = useCallback((query: string) => {
    setSearchQuery(query);
  }, []);

  const handleNodeClick = useCallback((node: GraphNodeObject) => {
    setSelectedNode(node);
    setIsPanelOpen(true);
  }, []);

  const handleNodeHover = useCallback((node: GraphNodeObject | null) => {
    if (!node) {
      setHighlightedNodes(new Set());
      return;
    }

    const highlighted = new Set<string>();
    highlighted.add(node.entity_id);

    if (graphData) {
      graphData.edges.forEach((edge) => {
        if (edge.source === node.entity_id) {
          highlighted.add(edge.target);
        } else if (edge.target === node.entity_id) {
          highlighted.add(edge.source);
        }
      });
    }

    setHighlightedNodes(highlighted);
  }, [graphData]);

  const handlePanelClose = useCallback(() => {
    setIsPanelOpen(false);
  }, []);

  const handleRetry = useCallback(() => {
    graphQuery.refetch();
  }, [graphQuery]);

  const isLoading = graphQuery.isLoading;
  const isError = graphQuery.isError;
  const isEmpty = !isLoading && !isError && (!graphData || graphData.nodes.length === 0);

  if (!currentTaskId) {
    return (
      <PageContainer>
        <NovelHeader title={novelTitle} />
        <div className="flex h-96 flex-col items-center justify-center gap-4">
          <div className="text-center">
            <h3 className="text-lg font-semibold text-text">请先选择分析任务</h3>
            <p className="mt-1 text-sm text-text-muted">
              使用顶部任务选择器选择一个已完成的任务以查看人物关系图谱
            </p>
          </div>
        </div>
      </PageContainer>
    );
  }

  return (
    <PageContainer className="flex flex-col">
      <NovelHeader title={novelTitle} />

      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3 }}
        className="mt-4 flex flex-1 flex-col"
      >
        <div className="mb-4">
          <GraphToolbar
            onZoomIn={handleZoomIn}
            onZoomOut={handleZoomOut}
            onFitToScreen={handleFitToScreen}
            onCenter={handleCenter}
            relationTypes={relationTypes}
            selectedRelationTypes={selectedRelationTypes}
            onRelationTypeChange={handleRelationTypeChange}
            searchQuery={searchQuery}
            onSearchChange={handleSearchChange}
          />
        </div>

        <div className="relative flex-1 overflow-hidden rounded-lg border border-border bg-surface">
          {isLoading ? (
            <div className="flex h-full min-h-[500px] w-full items-center justify-center">
              <div className="flex flex-col items-center gap-4">
                <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
                <span className="text-sm text-text-muted">正在加载图谱数据...</span>
              </div>
            </div>
          ) : isError ? (
            <div className="flex h-full min-h-[500px] flex-col items-center justify-center gap-4">
              <div className="text-center">
                <p className="text-base text-text">加载图谱数据失败</p>
                <p className="mt-1 text-sm text-text-muted">请检查网络连接后重试</p>
              </div>
              <Button variant="outline" size="sm" onClick={handleRetry} className="gap-2">
                <RefreshCw className="h-4 w-4" />
                重试
              </Button>
            </div>
          ) : isEmpty ? (
            <div className="flex h-full min-h-[500px] flex-col items-center justify-center gap-4">
              <div className="text-center">
                <p className="text-base text-text">暂无图谱数据</p>
                <p className="mt-1 text-sm text-text-muted">该任务尚未生成人物关系图谱</p>
              </div>
            </div>
          ) : (
            <>
              <ForceGraph2D
                ref={graphRef}
                graphData={forceGraphData}
                nodeId="entity_id"
                linkSource="source"
                linkTarget="target"
                nodeCanvasObject={(node, ctx, globalScale) => {
                  paintNode(node, ctx, globalScale, {
                    selectedNode,
                    highlightedNodes,
                    searchQuery,
                    nodeDegrees: getNodeDegrees(graphData!),
                  });
                }}
                linkCanvasObject={(link, ctx) => {
                  paintLink(link, ctx, {
                    highlightedNodes,
                    selectedRelationTypes,
                  });
                }}
                onNodeClick={handleNodeClick}
                onNodeHover={(node) => {
                  handleNodeHover(node as GraphNodeObject | null);
                  document.body.style.cursor = node ? "pointer" : "default";
                }}
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

              <div className="absolute bottom-4 left-4">
                <GraphLegend />
              </div>
            </>
          )}
        </div>
      </motion.div>

      <NodeDetailPanel
        node={selectedNode}
        relatedNodes={relatedNodes}
        isOpen={isPanelOpen}
        onClose={handlePanelClose}
      />
    </PageContainer>
  );
}

/* ------------------------------------------------------------------ */
/*  Helper Functions                                                  */
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

const NODE_SIZE_MIN = 8;
const NODE_SIZE_MAX = 40;
const LINK_WIDTH_MIN = 1;
const LINK_WIDTH_MAX = 4;
const LABEL_DEGREE_THRESHOLD = 3;

function getEntityColor(entityType: string): string {
  return ENTITY_TYPE_COLORS[entityType] || "hsl(234, 10%, 60%)";
}

function getRelationColor(relationType: string): string {
  return RELATION_TYPE_COLORS[relationType] || "hsl(234, 10%, 60%)";
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

function getNodeDegrees(data: GraphData): Map<string, number> {
  const degrees = new Map<string, number>();
  data.nodes.forEach((node) => {
    degrees.set(node.entity_id, 0);
  });
  data.edges.forEach((edge) => {
    degrees.set(edge.source, (degrees.get(edge.source) || 0) + 1);
    degrees.set(edge.target, (degrees.get(edge.target) || 0) + 1);
  });
  return degrees;
}

interface PaintNodeOptions {
  selectedNode: GraphNode | null;
  highlightedNodes: Set<string>;
  searchQuery: string;
  nodeDegrees: Map<string, number>;
}

function paintNode(
  node: GraphNodeObject,
  ctx: CanvasRenderingContext2D,
  globalScale: number,
  options: PaintNodeOptions
) {
  const { selectedNode, highlightedNodes, searchQuery, nodeDegrees } = options;

  const degree = nodeDegrees.get(node.entity_id) || 0;
  const degrees = Array.from(nodeDegrees.values());
  const minDegree = degrees.length > 0 ? Math.min(...degrees) : 0;
  const maxDegree = degrees.length > 0 ? Math.max(...degrees) : 1;

  let size = (NODE_SIZE_MIN + NODE_SIZE_MAX) / 2;
  if (maxDegree !== minDegree) {
    size = mapValue(degree, minDegree, maxDegree, NODE_SIZE_MIN, NODE_SIZE_MAX);
  }

  const isHighlighted = highlightedNodes.has(node.entity_id);
  const isSelected = selectedNode?.entity_id === node.entity_id;
  const isSearchMatched = searchQuery.trim() && node.name.toLowerCase().includes(searchQuery.toLowerCase());
  const showLabel = degree >= LABEL_DEGREE_THRESHOLD;

  const baseColor = getEntityColor(node.entity_type);
  let nodeColor = baseColor;
  let opacity = 1;

  if (highlightedNodes.size > 0 && !isHighlighted) {
    opacity = 0.2;
  }

  if (searchQuery && isSearchMatched) {
    nodeColor = "hsl(145, 55%, 48%)";
    opacity = 1;
  }

  ctx.globalAlpha = opacity;

  ctx.beginPath();
  ctx.arc(node.x || 0, node.y || 0, size, 0, 2 * Math.PI);
  ctx.fillStyle = nodeColor;
  ctx.fill();

  if (isSelected) {
    ctx.strokeStyle = "hsl(0, 0%, 100%)";
    ctx.lineWidth = 3;
    ctx.stroke();
  }

  if (isHighlighted && !isSelected) {
    ctx.strokeStyle = "hsl(0, 0%, 100%)";
    ctx.lineWidth = 2;
    ctx.stroke();
  }

  ctx.globalAlpha = 1;

  if (showLabel || isHighlighted || isSearchMatched) {
    const label = node.name;
    const fontSize = Math.max(10, 12 / globalScale);
    ctx.font = `${fontSize}px Sans-Serif`;
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    ctx.fillStyle = "hsl(234, 15%, 12%)";
    ctx.fillText(label, node.x || 0, (node.y || 0) + size + 2);
  }
}

interface PaintLinkOptions {
  highlightedNodes: Set<string>;
  selectedRelationTypes: Set<string>;
}

function paintLink(
  link: GraphLinkObject,
  ctx: CanvasRenderingContext2D,
  options: PaintLinkOptions
) {
  const { highlightedNodes, selectedRelationTypes } = options;

  const source = typeof link.source === "string" ? null : link.source;
  const target = typeof link.target === "string" ? null : link.target;

  if (!source || !target || !source.x || !source.y || !target.x || !target.y) return;

  if (selectedRelationTypes.size > 0 && link.relation_type && !selectedRelationTypes.has(link.relation_type)) {
    return;
  }

  const weight = link.weight ?? 1;
  const width = mapValue(weight, 1, 10, LINK_WIDTH_MIN, LINK_WIDTH_MAX);
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
  ctx.lineTo(target.x, target.y);
  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  ctx.stroke();
  ctx.globalAlpha = 1;
}

export default GraphPage;
