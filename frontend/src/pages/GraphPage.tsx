/**
 * GraphPage - 人物关系图谱页面
 *
 * 创建时间: 2026-04-05
 * 创建者: GLM-5
 * 任务: Phase 2-A 人物关系图谱页面实现
 * 说明: 展示人物关系力导向图，支持缩放、居中、关系类型过滤、节点搜索和详情面板
 *
 * 修改时间: 2026-04-05
 * 修改者: Code Review Fix
 * 修改内容:
 *   - 重构为使用封装的 ForceGraph 组件，消除重复的 paintNode/paintLink/颜色常量代码
 *   - 移除 ~180 行内联渲染逻辑，统一由 components/charts/ForceGraph.tsx 管理
 */
import { useEffect, useState, useCallback, useMemo, useRef } from "react";
import { useParams, useSearchParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { getGraph, getCharacters } from "@/api/results";
import { getNovel } from "@/api/novels";
import { useNovelStore } from "@/store/novelStore";
import { PageContainer } from "@/components/layout/PageContainer";
import { NovelHeader } from "@/components/common/NovelHeader";
import { ForceGraph } from "@/components/charts/ForceGraph";
import { type ForceGraphHandle } from "@/components/charts/ForceGraph";
import { GraphToolbar } from "@/components/charts/GraphToolbar";
import { NodeDetailPanel, type RelatedNodeInfo } from "@/components/charts/NodeDetailPanel";
import { GraphLegend } from "@/components/charts/GraphLegend";
import { Button } from "@/components/ui/button";
import { RefreshCw } from "lucide-react";
import type { GraphNode, GraphNodeObject } from "@/api/types";

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

  // ForceGraph 组件引用（用于外部控制缩放/居中）
  const forceGraphRef = useRef<ForceGraphHandle>(null);

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

  // 调用 /characters API 获取出场次数，用于更准确的节点大小映射
  // 设计文档 §2.5 要求：节点大小根据"出场次数/度中心性"线性缩放
  const charactersQuery = useQuery({
    queryKey: ["characters", novelId, currentTaskId],
    queryFn: () => getCharacters(novelId!, currentTaskId!),
    enabled,
    staleTime: STALE_TIME,
  });

  // 构建节点标识 → 出场次数的 Map（供 ForceGraph 使用）
  // 注意：/characters API 返回的 Character 只有 name 字段（无 entity_id），
  // 而 /graph API 返回的 GraphNode 有 entity_id 和 name。
  // 这里使用 name 作为 key，ForceGraph.getNodeSize 会先按 entity_id 查，
  // 查不到时再按 name 查。
  const appearanceCountMap = useMemo((): Map<string, number> | undefined => {
    if (!charactersQuery.data || charactersQuery.data.length === 0) return undefined;
    const map = new Map<string, number>();
    charactersQuery.data.forEach((char) => {
      map.set(char.name, char.appearance_count);
    });
    return map;
  }, [charactersQuery.data]);

  const novelQuery = useQuery({
    queryKey: ["novel", novelId],
    queryFn: () => getNovel(novelId!),
    enabled: !!novelId,
    staleTime: STALE_TIME,
  });

  const novelTitle = novelQuery.data?.title ?? "小说详情";

  const graphData = graphQuery.data;

  // 从实际数据中提取所有关系类型（动态）
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

  // 从实际数据中提取所有实体类型（供图例使用）
  const entityTypes = useMemo(() => {
    if (!graphData?.nodes) return [];
    const types = new Set<string>();
    graphData.nodes.forEach((node) => {
      types.add(node.entity_type);
    });
    return Array.from(types);
  }, [graphData]);

  // 计算选中节点的关联节点列表
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

  /* ---- Toolbar 回调 ---- */

  const handleZoomIn = useCallback(() => {
    forceGraphRef.current?.zoomIn();
  }, []);

  const handleZoomOut = useCallback(() => {
    forceGraphRef.current?.zoomOut();
  }, []);

  const handleFitToScreen = useCallback(() => {
    forceGraphRef.current?.fitToScreen();
  }, []);

  const handleCenter = useCallback(() => {
    forceGraphRef.current?.center();
  }, []);

  const handleRelationTypeChange = useCallback((types: Set<string>) => {
    setSelectedRelationTypes(types);
  }, []);

  const handleSearchChange = useCallback((query: string) => {
    setSearchQuery(query);
  }, []);

  /* ---- 图谱交互回调 ---- */

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
        {/* 工具栏 */}
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

        {/* 图谱区域 */}
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
              {/* 使用封装的 ForceGraph 组件 */}
              <ForceGraph
                ref={forceGraphRef}
                data={graphData!}
                selectedNode={selectedNode}
                onNodeClick={handleNodeClick}
                onNodeHover={handleNodeHover}
                highlightedNodes={highlightedNodes}
                searchQuery={searchQuery}
                relationFilter={selectedRelationTypes}
                appearanceCountMap={appearanceCountMap}
                className="absolute inset-0"
              />

              {/* 动态图例：根据实际数据生成 */}
              <div className="absolute bottom-4 left-4 z-10">
                <GraphLegend
                  entityTypes={entityTypes}
                  relationTypes={relationTypes}
                />
              </div>
            </>
          )}
        </div>
      </motion.div>

      {/* 节点详情面板 */}
      <NodeDetailPanel
        node={selectedNode}
        relatedNodes={relatedNodes}
        isOpen={isPanelOpen}
        onClose={handlePanelClose}
      />
    </PageContainer>
  );
}

export default GraphPage;
