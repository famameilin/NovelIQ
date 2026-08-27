/**
 * GraphPage - 图谱分析入口页面
 */
import { useEffect, useMemo, useRef, useState, useCallback } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import {
  AlertTriangle,
  Network,
  RefreshCw,
} from "lucide-react";
import { isAnalysisNotCompleteError, getAnalysisNotCompleteRunStatus } from "@/api/errorGuards";
import { getCharacters, getGraph } from "@/api/results";
import { getNovel } from "@/api/novels";
import { useNovelStore } from "@/store/novelStore";
import { AnalysisNotCompleteState } from "@/components/common/AnalysisNotCompleteState";
import { AnalysisWorkspace } from "@/components/layout/AnalysisWorkspace";
import { NodeDetailPanel, type RelatedNodeInfo } from "@/components/charts/NodeDetailPanel";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import type { GraphNode } from "@/api/types";
import type { ForceGraphHandle, GraphNodeObject } from "@/components/charts/forceGraphTypes";
import { GraphOverviewSection } from "@/pages/graph/GraphOverviewSection";
import { GraphWorkspaceSection } from "@/pages/graph/GraphWorkspaceSection";
import { buildGraphUrl, buildTimelineUrl } from "@/pages/graph/graphPageNavigation";
import { useGraphDeepLinkSelection } from "@/pages/graph/useGraphDeepLinkSelection";
import { useGraphChangePagination } from "@/pages/graph/useGraphChangePagination";

const STALE_TIME = 5 * 60 * 1000;
const pageSectionVariants = {
  hidden: { opacity: 0, y: 16 },
  visible: { opacity: 1, y: 0 },
};

const changeTypeLabels: Record<string, string> = {
  assert: "建立",
  reinforce: "强化",
  weaken: "弱化",
  break: "断裂",
  refine: "修订",
  supersede: "替代",
  retract: "撤回",
};

function getChangeTypeLabel(changeType?: string | null): string {
  if (!changeType) return "变化";
  return changeTypeLabels[changeType] ?? changeType;
}

/**
 * 2026-04-28，任务：分析详情页单屏 Tabs 改造
 * 修改原因：图谱页改为画布优先的 tab 工作台，关系变化和摘要不再挤占首屏画布空间
 */
export function GraphPage() {
  const { novelId } = useParams<{ novelId: string }>();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { currentNovelId, currentTaskId, setNovel, setTask } = useNovelStore();

  const urlTaskId = searchParams.get("task_id");
  const urlSelectedChapter = searchParams.get("selected_chapter");
  const urlChangeId = searchParams.get("change_id");
  const forceGraphRef = useRef<ForceGraphHandle>(null);
  const urlTaskSyncRef = useRef<string | null>(urlTaskId && currentTaskId !== urlTaskId ? urlTaskId : null);

  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedRelationTypes, setSelectedRelationTypes] = useState<Set<string>>(new Set());
  const [isPanelOpen, setIsPanelOpen] = useState(false);
  const previousTaskIdRef = useRef<string | null | undefined>(undefined);
  const storeTaskId = currentNovelId === novelId ? currentTaskId : null;
  const taskScopeId = urlTaskId ?? storeTaskId;

  useEffect(() => {
    if (novelId) {
      setNovel(novelId);
      if (urlTaskId) {
        if (storeTaskId !== urlTaskId) {
          urlTaskSyncRef.current = urlTaskId;
        }
        setTask(urlTaskId);
      }
    }
  }, [novelId, setNovel, setTask, urlTaskId]); // eslint-disable-line react-hooks/exhaustive-deps -- storeTaskId intentionally excluded: this syncs URL→store, not store→URL

  useEffect(() => {
    if (!novelId || !storeTaskId) {
      return;
    }

    // URL 上带 task_id 的首屏 deep-link 必须先等 store 同步到同一 task，
    // 不能让旧 store 状态抢先回写 URL；否则会把合法 deep-link 误改成旧任务
    if (urlTaskId === storeTaskId) {
      if (urlTaskSyncRef.current === storeTaskId) {
        urlTaskSyncRef.current = null;
      }
      return;
    }
    if (urlTaskId && urlTaskSyncRef.current === urlTaskId) {
      return;
    }

    navigate(buildGraphUrl(novelId, storeTaskId), { replace: true });
  }, [navigate, novelId, storeTaskId, urlTaskId]);

  const enabled = !!novelId && !!taskScopeId;

  const graphQuery = useQuery({
    queryKey: ["graph", novelId, taskScopeId],
    queryFn: () => getGraph(novelId!, taskScopeId!),
    enabled,
    staleTime: STALE_TIME,
  });

  const charactersQuery = useQuery({
    queryKey: ["characters", novelId, taskScopeId],
    queryFn: () => getCharacters(novelId!, taskScopeId!),
    // appearanceCountMap 是图谱页面正式视觉语义的一部分；
    // 这里只在 `/graph` 主查询成功后再请求 `/characters`，避免旧 run 或主查询失败时
    // 并发打出第二条旁路状态链
    enabled: enabled && graphQuery.isSuccess,
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
  const appearanceCountMap = useMemo((): Map<string, number> | undefined => {
    if (!charactersQuery.data || charactersQuery.data.length === 0) return undefined;
    const map = new Map<string, number>();
    charactersQuery.data.forEach((character) => {
      map.set(character.name, character.appearance_count);
    });
    return map;
  }, [charactersQuery.data]);

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

  const entityTypes = useMemo(() => {
    if (!graphData?.nodes) return [];
    const types = new Set<string>();
    graphData.nodes.forEach((node) => {
      types.add(node.entity_type);
    });
    return Array.from(types);
  }, [graphData]);

  const relatedNodes = useMemo((): RelatedNodeInfo[] => {
    if (!selectedNode || !graphData) return [];

    const related: RelatedNodeInfo[] = [];
    const nodeMap = new Map<number, GraphNode>();
    graphData.nodes.forEach((node) => {
      nodeMap.set(node.entity_id, node);
    });

    graphData.edges.forEach((edge) => {
      if (edge.source_entity_id === selectedNode.entity_id) {
        const targetNode = nodeMap.get(edge.target_entity_id);
        if (targetNode) {
          related.push({
            node: targetNode,
            relationType: edge.relation_type,
          });
        }
      } else if (edge.target_entity_id === selectedNode.entity_id) {
        const sourceNode = nodeMap.get(edge.source_entity_id);
        if (sourceNode) {
          related.push({
            node: sourceNode,
            relationType: edge.relation_type,
          });
        }
      }
    });

    return related.sort((left, right) => left.relationType.localeCompare(right.relationType));
  }, [selectedNode, graphData]);

  const {
    changesLoadError,
    handleLoadMoreChanges,
    hasMoreChanges,
    isChangesLoading,
    loadedChangeCount,
    loadedChanges,
    sortedChanges,
    totalChangeCount,
  } = useGraphChangePagination({
    novelId,
    taskScopeId,
  });

  const timelineUrl = novelId && taskScopeId ? buildTimelineUrl(novelId, taskScopeId) : null;
  const {
    activeSelectedChangeId,
    graphSelectionHint,
    handleGoTimeline,
    handleOpenTimelineChapter,
    handleSelectChange,
    selectedChange,
  } = useGraphDeepLinkSelection({
    novelId,
    taskScopeId,
    timelineUrl,
    urlChangeId,
    urlSelectedChapter,
    loadedChanges,
    sortedChanges,
    navigate,
  });

  useEffect(() => {
    const previousTaskId = previousTaskIdRef.current;
    previousTaskIdRef.current = taskScopeId;
    if (previousTaskId === undefined || previousTaskId === taskScopeId) {
      return;
    }

    // GraphPage 自己只负责清理页面级展示状态；事件窗口分页和 deep-link 自动选中
    // 已分别下沉到独立 hook，避免 task 切换时多个职责互相踩状态
    // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional state reset on task change
    setSelectedNode(null);
    setIsPanelOpen(false);
    setSearchQuery("");
    setSelectedRelationTypes(new Set());
  }, [taskScopeId]);

  const activeRelationCount = useMemo(
    () => graphData?.edges.filter((edge) => edge.is_active).length ?? 0,
    [graphData]
  );

  const inactiveRelationCount = useMemo(
    () => graphData?.edges.filter((edge) => !edge.is_active).length ?? 0,
    [graphData]
  );
  const graphDensity = useMemo(() => {
    const nodeCount = graphData?.nodes.length ?? 0;
    if (nodeCount < 2) {
      return 0;
    }
    return activeRelationCount / ((nodeCount * (nodeCount - 1)) / 2);
  }, [activeRelationCount, graphData]);

  const isAnalysisNotComplete =
    isAnalysisNotCompleteError(graphQuery.error) || isAnalysisNotCompleteError(charactersQuery.error);
  const analysisFailed =
    getAnalysisNotCompleteRunStatus(graphQuery.error) === "failed" ||
    getAnalysisNotCompleteRunStatus(charactersQuery.error) === "failed";
  const isLoading = graphQuery.isLoading || charactersQuery.isLoading;
  const isError = (graphQuery.isError || charactersQuery.isError) && !isAnalysisNotComplete;
  const isEmpty = !isLoading && !isError && (!graphData || graphData.nodes.length === 0);

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

  const handleNodeClick = useCallback((node: GraphNodeObject) => {
    setSelectedNode(node);
    setIsPanelOpen(true);
  }, []);

  const handleRetry = useCallback(() => {
    graphQuery.refetch();
    charactersQuery.refetch();
  }, [charactersQuery, graphQuery]);

  // 2026-04-28，任务：分析详情页单屏 Tabs 改造
  // 修改原因：图谱页默认展示关系画布，关系变化和摘要拆入后续 tab，避免 overview 把画布挤到首屏之外
  const graphWorkspaceProps = {
    graphData: graphData!,
    forceGraphRef,
    onNodeClick: handleNodeClick,
    searchQuery,
    selectedRelationTypes,
    appearanceCountMap,
    entityTypes,
    relationTypes,
    onZoomIn: handleZoomIn,
    onZoomOut: handleZoomOut,
    onFitToScreen: handleFitToScreen,
    onCenter: handleCenter,
    onRelationTypeChange: handleRelationTypeChange,
    onSearchChange: handleSearchChange,
    totalChangeCount,
    loadedChangeCount,
    hasMoreChanges,
    isChangesLoading,
    changesLoadError,
    graphSelectionHint,
    sortedChanges,
    activeSelectedChangeId,
    onSelectChange: handleSelectChange,
    onLoadMoreChanges: handleLoadMoreChanges,
    onGoTimeline: handleGoTimeline,
    timelineUrl,
    selectedNode,
    onOpenTimelineChapter: handleOpenTimelineChapter,
    selectedChange,
    pageSectionVariants,
    getChangeTypeLabel,
  };

  const renderLoadedContent = () => (
    <AnalysisWorkspace.Tabs defaultValue="graph">
      <AnalysisWorkspace.Tab value="graph" label="关系图谱">
        <GraphWorkspaceSection {...graphWorkspaceProps} view="graph" />
      </AnalysisWorkspace.Tab>
      <AnalysisWorkspace.Tab value="changes" label="图谱变化">
        <GraphWorkspaceSection {...graphWorkspaceProps} view="changes" />
      </AnalysisWorkspace.Tab>
      <AnalysisWorkspace.Tab value="summary" label="快照概览">
        <div className="h-full overflow-hidden">
          <GraphOverviewSection
            graphData={graphData!}
            activeRelationCount={activeRelationCount}
            inactiveRelationCount={inactiveRelationCount}
            graphDensity={graphDensity}
            loadedChangeCount={loadedChangeCount}
            totalChangeCount={totalChangeCount}
            pageSectionVariants={pageSectionVariants}
          />
        </div>
      </AnalysisWorkspace.Tab>
    </AnalysisWorkspace.Tabs>
  );

  // GraphPage 也需要和 TimelinePage 一样先兜住路由缺参空态，
  // 避免 novelId 缺失时继续渲染图谱分析入口，造成“页面存在但上下文不存在”的假象
  if (!novelId) {
    return (
      <AnalysisWorkspace title="图谱分析">
        <div className="flex h-96 flex-col items-center justify-center gap-4">
          <div className="text-center">
            <h3 className="text-lg font-semibold text-text">小说不存在</h3>
            <p className="mt-1 text-sm text-text-muted">
              当前图谱入口缺少小说上下文，请从小说列表重新进入。
            </p>
          </div>
        </div>
      </AnalysisWorkspace>
    );
  }

  if (!taskScopeId) {
    return (
      <AnalysisWorkspace title={novelTitle}>
        <div className="flex h-96 flex-col items-center justify-center gap-4">
          <div className="text-center">
            <h3 className="text-lg font-semibold text-text">请先选择分析任务</h3>
            <p className="mt-1 text-sm text-text-muted">
              使用顶部任务选择器选择一个已完成的任务以查看图谱分析入口
            </p>
          </div>
        </div>
      </AnalysisWorkspace>
    );
  }

  return (
    <AnalysisWorkspace title={novelTitle}>
      <div className="flex min-h-0 flex-1 flex-col">
        {isLoading ? (
          <motion.section
            variants={pageSectionVariants}
            initial="hidden"
            animate="visible"
            transition={{ duration: 0.28, delay: 0.05 }}
          >
            <Card variant="elevated" className="rounded-2xl">
              <CardContent className="space-y-4 p-6">
                <div className="flex items-center gap-3">
                  <div className="h-6 w-6 animate-spin rounded-full border-2 border-primary border-t-transparent" />
                  <div>
                    <p className="text-sm font-medium text-text">正在加载人物关系图谱</p>
                    <p className="text-sm text-text-muted">准备关系概览和变化记录。</p>
                  </div>
                </div>
                <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                  {Array.from({ length: 4 }).map((_, index) => (
                    <div
                      key={index}
                      className="h-32 animate-pulse rounded-xl border border-border bg-surface-hover/60"
                    />
                  ))}
                </div>
              </CardContent>
            </Card>
          </motion.section>
        ) : isAnalysisNotComplete ? (
          <motion.section
            variants={pageSectionVariants}
            initial="hidden"
            animate="visible"
            transition={{ duration: 0.28, delay: 0.05 }}
          >
            <AnalysisNotCompleteState
              title={analysisFailed ? "图谱分析任务已失败" : "图谱结果尚未完成"}
              description={
                analysisFailed
                  ? "该分析任务已失败，人物关系图谱和关系变化记录无法读取，请重新发起分析后再查看。"
                  : "当前任务仍在分析中，人物关系图谱和关系变化记录暂时不可读，请等待任务进入完成态后再查看。"
              }
              failed={analysisFailed}
            />
          </motion.section>
        ) : isError ? (
          <motion.section
            variants={pageSectionVariants}
            initial="hidden"
            animate="visible"
            transition={{ duration: 0.28, delay: 0.05 }}
          >
            <Card variant="elevated" className="rounded-2xl">
              <CardContent className="flex flex-col items-center gap-4 p-10 text-center">
                <AlertTriangle className="h-10 w-10 text-chart-negative" />
                <div className="space-y-1">
                  <p className="text-base font-semibold text-text">图谱数据加载失败</p>
                  <p className="text-sm text-text-muted">请检查后端服务或任务状态后重试。</p>
                </div>
                <Button variant="outline" size="sm" onClick={handleRetry}>
                  <RefreshCw className="h-4 w-4" />
                  重试
                </Button>
              </CardContent>
            </Card>
          </motion.section>
        ) : isEmpty ? (
          <motion.section
            variants={pageSectionVariants}
            initial="hidden"
            animate="visible"
            transition={{ duration: 0.28, delay: 0.05 }}
          >
            <Card variant="elevated" className="rounded-2xl">
              <CardContent className="flex flex-col items-center gap-4 p-10 text-center">
                <Network className="h-10 w-10 text-text-muted" />
                <div className="space-y-1">
                  <p className="text-base font-semibold text-text">该任务暂时没有可展示的关系图谱</p>
                  <p className="text-sm text-text-muted">完成图谱分析后，这里会自动显示关系概览和变化记录。</p>
                </div>
              </CardContent>
            </Card>
          </motion.section>
        ) : (
          renderLoadedContent()
        )}
      </div>

      <NodeDetailPanel
        node={selectedNode}
        relatedNodes={relatedNodes}
        isOpen={isPanelOpen}
        onClose={() => setIsPanelOpen(false)}
      />
    </AnalysisWorkspace>
  );
}

export default GraphPage;
