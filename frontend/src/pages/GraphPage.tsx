/**
 * GraphPage - 图谱分析入口页面
 */
import { useEffect, useMemo, useRef, useState, useCallback } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  History,
  Link2,
  Network,
  RefreshCw,
  Sparkles,
  Users,
} from "lucide-react";
import { getCharacters, getGraph, getGraphEvents } from "@/api/results";
import { getNovel } from "@/api/novels";
import { useNovelStore } from "@/store/novelStore";
import { cn } from "@/lib/cn";
import { PageContainer } from "@/components/layout/PageContainer";
import { NovelHeader } from "@/components/common/NovelHeader";
import { DashboardCardShell } from "@/components/common/DashboardCardShell";
import { MetricCard } from "@/components/common/MetricCard";
import { ForceGraph } from "@/components/charts/ForceGraph";
import { GraphToolbar } from "@/components/charts/GraphToolbar";
import { GraphLegend } from "@/components/charts/GraphLegend";
import { NodeDetailPanel, type RelatedNodeInfo } from "@/components/charts/NodeDetailPanel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { ForceGraphHandle, GraphEdge, GraphEvent, GraphEventsPageInfo, GraphNode, GraphNodeObject } from "@/api/types";

const STALE_TIME = 5 * 60 * 1000;
const pageSectionVariants = {
  hidden: { opacity: 0, y: 16 },
  visible: { opacity: 1, y: 0 },
};

const changeTypeLabels: Record<string, string> = {
  无变化: "延续",
  新建: "建立",
  强化: "强化",
  弱化: "弱化",
  断裂: "断裂",
};

function buildGraphUrl(
  novelId: string,
  taskId: string,
  options?: { chunkId?: number | null; relationEventId?: number | null }
): string {
  const params = new URLSearchParams({ task_id: taskId });
  if (options?.chunkId != null) {
    params.set("selected_chunk", String(options.chunkId));
  }
  if (options?.relationEventId != null) {
    params.set("relation_event_id", String(options.relationEventId));
  }
  return `/novels/${novelId}/graph?${params.toString()}`;
}

function buildTimelineUrl(novelId: string, taskId: string): string {
  return `/novels/${novelId}/timeline?task_id=${taskId}&max_level=3&show_tension=true`;
}

function buildTimelineSelectionUrl(baseUrl: string, options?: { chunkId?: number | null; relationEventId?: number | null }): string {
  const params: string[] = [];
  if (options?.chunkId != null) {
    params.push(`selected_chunk=${options.chunkId}`);
  }
  if (options?.relationEventId != null) {
    params.push(`relation_event_id=${options.relationEventId}`);
  }
  if (params.length === 0) {
    return baseUrl;
  }
  return `${baseUrl}&${params.join("&")}`;
}

function getChangeTypeLabel(changeType?: string | null): string {
  if (!changeType) return "变化";
  return changeTypeLabels[changeType] ?? changeType;
}

function getEdgeDisplayNames(edge: GraphEdge, nodeNameMap: Map<string, string>): { from: string; to: string } {
  return {
    from: edge.from_name ?? nodeNameMap.get(edge.source) ?? edge.source,
    to: edge.to_name ?? nodeNameMap.get(edge.target) ?? edge.target,
  };
}

function mergeGraphEvents(existingEvents: GraphEvent[], incomingEvents: GraphEvent[]): GraphEvent[] {
  const merged = new Map<number, GraphEvent>();
  existingEvents.forEach((event) => {
    merged.set(event.relation_event_id, event);
  });
  incomingEvents.forEach((event) => {
    merged.set(event.relation_event_id, event);
  });
  return Array.from(merged.values());
}

export function GraphPage() {
  const { novelId } = useParams<{ novelId: string }>();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { currentNovelId, currentTaskId, setNovel, setTask } = useNovelStore();

  const urlTaskId = searchParams.get("task_id");
  const urlSelectedChunk = searchParams.get("selected_chunk");
  const urlRelationEventId = searchParams.get("relation_event_id");
  const forceGraphRef = useRef<ForceGraphHandle>(null);
  const urlTaskSyncRef = useRef<string | null>(urlTaskId && currentTaskId !== urlTaskId ? urlTaskId : null);

  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedRelationTypes, setSelectedRelationTypes] = useState<Set<string>>(new Set());
  const [isPanelOpen, setIsPanelOpen] = useState(false);
  const [selectedEventId, setSelectedEventId] = useState<number | null>(null);
  const [hasUserSelectedEvent, setHasUserSelectedEvent] = useState(false);
  const [loadedEvents, setLoadedEvents] = useState<GraphEvent[]>([]);
  const [eventsPageInfo, setEventsPageInfo] = useState<GraphEventsPageInfo | null>(null);
  const [isEventsLoading, setIsEventsLoading] = useState(false);
  const [eventsLoadError, setEventsLoadError] = useState<string | null>(null);
  const eventsRequestVersionRef = useRef(0);
  const currentTaskScopeIdRef = useRef<string | null>(null);
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
  }, [novelId, setNovel, setTask, urlTaskId]);

  useEffect(() => {
    if (!novelId || !storeTaskId) {
      return;
    }

    // 中文注释：URL 上带 task_id 的首屏 deep-link 必须先等 store 同步到同一 task，
    // 不能让旧 store 状态抢先回写 URL；否则会把合法 deep-link 误改成旧任务。
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

  useEffect(() => {
    currentTaskScopeIdRef.current = taskScopeId;
  }, [taskScopeId]);

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
  const graphContractIssue =
    enabled &&
    !!graphData &&
    (graphData.summary == null || graphData.quality == null || graphData.events_page == null);

  const resetTaskScopedGraphState = useCallback(
    (options?: { events?: GraphEvent[]; pageInfo?: GraphEventsPageInfo | null }) => {
      // 中文注释：图谱页的选中态、分页窗口、加载错误都绑定当前 task。
      // 只要 task 变了，或者拿到了新的 graph snapshot，就必须整包重置，
      // 防止旧任务的事件窗口、错误提示和节点选择残留到新页面。
      setSelectedNode(null);
      setIsPanelOpen(false);
      setSearchQuery("");
      setSelectedRelationTypes(new Set());
      setSelectedEventId(null);
      setHasUserSelectedEvent(false);
      setLoadedEvents(options?.events ?? []);
      setEventsPageInfo(options?.pageInfo ?? null);
      setEventsLoadError(null);
      setIsEventsLoading(false);
    },
    []
  );

  const appearanceCountMap = useMemo((): Map<string, number> | undefined => {
    if (!charactersQuery.data || charactersQuery.data.length === 0) return undefined;
    const map = new Map<string, number>();
    charactersQuery.data.forEach((character) => {
      map.set(character.name, character.appearance_count);
    });
    return map;
  }, [charactersQuery.data]);

  const nodeNameMap = useMemo(() => {
    const map = new Map<string, string>();
    graphData?.nodes.forEach((node) => {
      map.set(node.entity_id, node.name);
    });
    return map;
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

    return related.sort((left, right) => right.weight - left.weight);
  }, [selectedNode, graphData]);

  // /graph 返回的是 product-layer summary/quality，而不是 authority 原始事实；
  // 页面可以自由调整展示摘要，但不应反向定义 authority 语义。
  const graphSummary = graphData?.summary ?? null;

  const sortedEvents = useMemo(() => {
    return [...loadedEvents].sort((left, right) => {
      const chunkDiff = right.chunk_id - left.chunk_id;
      if (chunkDiff !== 0) return chunkDiff;
      return right.relation_event_id - left.relation_event_id;
    });
  }, [loadedEvents]);

  const totalEventCount = eventsPageInfo?.total ?? sortedEvents.length;
  const hasMoreEvents = eventsPageInfo?.has_more ?? false;
  const loadedEventCount = sortedEvents.length;

  const initialRelationEventId = useMemo(() => {
    if (!urlRelationEventId) return null;
    const parsed = Number(urlRelationEventId);
    return Number.isInteger(parsed) ? parsed : null;
  }, [urlRelationEventId]);
  const initialSelectedChunk = useMemo(() => {
    if (!urlSelectedChunk) return null;
    const parsed = Number(urlSelectedChunk);
    return Number.isInteger(parsed) ? parsed : null;
  }, [urlSelectedChunk]);
  const selectedEvent = useMemo(() => {
    if (sortedEvents.length === 0) return null;
    if (selectedEventId == null) {
      return initialRelationEventId != null || initialSelectedChunk != null ? null : sortedEvents[0];
    }
    return sortedEvents.find((event) => event.relation_event_id === selectedEventId) ?? null;
  }, [initialRelationEventId, initialSelectedChunk, sortedEvents, selectedEventId]);
  const activeSelectedEventId = selectedEvent?.relation_event_id ?? null;
  const deepLinkResolvedEventId = useMemo(() => {
    if (initialRelationEventId != null) {
      const matchedEvent = sortedEvents.find((event) => event.relation_event_id === initialRelationEventId);
      if (matchedEvent) {
        return matchedEvent.relation_event_id;
      }
      if (initialSelectedChunk != null) {
        const fallbackEvent = sortedEvents.find((event) => event.chunk_id === initialSelectedChunk);
        return fallbackEvent?.relation_event_id ?? null;
      }
      return null;
    }
    if (initialSelectedChunk != null) {
      const chunkMatchedEvent = sortedEvents.find((event) => event.chunk_id === initialSelectedChunk);
      return chunkMatchedEvent?.relation_event_id ?? null;
    }
    return null;
  }, [initialRelationEventId, initialSelectedChunk, sortedEvents]);
  const graphSelectionHint = useMemo(() => {
    if (hasUserSelectedEvent) {
      return null;
    }
    if (activeSelectedEventId != null && (deepLinkResolvedEventId == null || activeSelectedEventId !== deepLinkResolvedEventId)) {
      return null;
    }
    if (initialRelationEventId == null && initialSelectedChunk == null) {
      return null;
    }
    if (initialRelationEventId != null) {
      const matchedEvent = sortedEvents.find((event) => event.relation_event_id === initialRelationEventId);
      if (matchedEvent) {
        return null;
      }
      if (initialSelectedChunk != null) {
        const fallbackEvent = sortedEvents.find((event) => event.chunk_id === initialSelectedChunk);
        if (fallbackEvent) {
          return "未在当前事件窗口定位到指定关系事件，已回退到同一时间节点的关系变化。";
        }
      }
      return "未在当前图谱事件窗口定位到指定关系事件。";
    }
    if (initialSelectedChunk != null) {
      const chunkMatchedEvent = sortedEvents.find((event) => event.chunk_id === initialSelectedChunk);
      if (!chunkMatchedEvent) {
        return "未在当前事件窗口定位到指定时间节点的关系变化。";
      }
    }
    return null;
  }, [activeSelectedEventId, deepLinkResolvedEventId, hasUserSelectedEvent, initialRelationEventId, initialSelectedChunk, sortedEvents]);

  useEffect(() => {
    if (!graphData) {
      return;
    }

    // Bump the request version whenever the snapshot changes so late load-more
    // responses from the previous task/view are ignored instead of polluting
    // the current page-level history window.
    eventsRequestVersionRef.current += 1;
    // 中文注释：同一 task 的 snapshot 刷新只同步最新首屏数据与分页元信息，
    // 不应把用户当前选中的节点、事件详情和已展开的历史窗口整包清空。
    setLoadedEvents((currentEvents) =>
      currentEvents.length > 0 ? mergeGraphEvents(currentEvents, graphData.events ?? []) : (graphData.events ?? [])
    );
    setEventsPageInfo(graphData.events_page ?? null);
    setEventsLoadError(null);
    setIsEventsLoading(false);
    setSelectedNode((currentSelectedNode) => {
      if (!currentSelectedNode) {
        return null;
      }
      const nextSelectedNode =
        graphData.nodes.find((node) => node.entity_id === currentSelectedNode.entity_id) ?? null;
      if (nextSelectedNode == null) {
        setIsPanelOpen(false);
      }
      return nextSelectedNode;
    });
  }, [graphData]);

  useEffect(() => {
    setHasUserSelectedEvent(false);
  }, [initialRelationEventId, initialSelectedChunk, taskScopeId]);

  useEffect(() => {
    if (hasUserSelectedEvent) return;
    if (initialRelationEventId == null && initialSelectedChunk == null) return;

    const matchedEvent =
      initialRelationEventId != null
        ? loadedEvents.find((event) => event.relation_event_id === initialRelationEventId) ?? null
        : null;
    if (matchedEvent) {
      setSelectedEventId(matchedEvent.relation_event_id);
      return;
    }

    const fallbackEvent =
      initialSelectedChunk != null
        ? loadedEvents.find((event) => event.chunk_id === initialSelectedChunk) ?? null
        : null;
    if (fallbackEvent) {
      setSelectedEventId(fallbackEvent.relation_event_id);
      return;
    }

    setSelectedEventId(null);
  }, [hasUserSelectedEvent, initialRelationEventId, initialSelectedChunk, loadedEvents]);

  useEffect(() => {
    const previousTaskId = previousTaskIdRef.current;
    previousTaskIdRef.current = taskScopeId;
    // 中文注释：这里只处理“真实 task 变化”后的页面清理。
    // 首次挂载若已命中 React Query 缓存，不应把刚同步进来的 events/pageInfo
    // 又立即清空，否则会出现 graph 已有数据但 events 侧栏为空的回归。
    if (previousTaskId === undefined || previousTaskId === taskScopeId) {
      return;
    }
    // 中文注释：task 切换发生在新快照返回之前时，也要立即清掉旧页面状态；
    // 否则 load-more 报错、旧 deep-link 提示、旧选中节点会短暂闪回到新 task 页面。
    eventsRequestVersionRef.current += 1;
    // 中文注释：如果新 task 已经命中 React Query 缓存，就用当前 snapshot 直接回填
    // events/pageInfo；这样既能清掉旧 task 的脏状态，也不会把新 task 的已缓存窗口误清空。
    resetTaskScopedGraphState(
      graphData
        ? {
            events: graphData.events ?? [],
            pageInfo: graphData.events_page ?? null,
          }
        : undefined
    );
  }, [graphData, resetTaskScopedGraphState, taskScopeId]);

  useEffect(() => {
    if (!graphContractIssue || !graphData) return;

    const missingFields = [
      graphData.summary ? null : "summary",
      graphData.quality ? null : "quality",
      graphData.events_page ? null : "events_page",
    ].filter(Boolean);

    console.error("[GraphPage] /graph authority contract is missing required fields:", {
      taskId: taskScopeId,
      missingFields,
    });
  }, [graphContractIssue, graphData, taskScopeId]);

  const weakRelations = useMemo(() => {
    if (!graphData) return [];
    return [...graphData.edges]
      .sort((left, right) => {
        const weightDiff = (left.weight ?? 1) - (right.weight ?? 1);
        if (weightDiff !== 0) return weightDiff;
        return (right.change_count ?? 0) - (left.change_count ?? 0);
      })
      .slice(0, 5)
      .map((edge) => ({
        ...edge,
        ...getEdgeDisplayNames(edge, nodeNameMap),
      }));
  }, [graphData, nodeNameMap]);

  const activeRelationCount = useMemo(
    () => graphData?.edges.filter((edge) => edge.is_active !== false).length ?? 0,
    [graphData]
  );

  const inactiveRelationCount = useMemo(
    () => graphData?.edges.filter((edge) => edge.is_active === false).length ?? 0,
    [graphData]
  );

  const timelineUrl = novelId && taskScopeId ? buildTimelineUrl(novelId, taskScopeId) : null;
  const isLoading = graphQuery.isLoading;
  const isError = graphQuery.isError;
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
  }, [graphQuery]);

  const handleLoadMoreEvents = useCallback(async () => {
    if (!novelId || !taskScopeId || !eventsPageInfo?.next_cursor || isEventsLoading) {
      return;
    }

    const requestTaskId = taskScopeId;
    const requestCursor = eventsPageInfo.next_cursor;
    const requestVersion = eventsRequestVersionRef.current + 1;
    eventsRequestVersionRef.current = requestVersion;

    setIsEventsLoading(true);
    setEventsLoadError(null);
    try {
      const page = await getGraphEvents(novelId, taskScopeId, {
        eventsCursor: requestCursor,
        eventsLimit: eventsPageInfo.limit,
      });
      if (eventsRequestVersionRef.current !== requestVersion || currentTaskScopeIdRef.current !== requestTaskId) {
        return;
      }
      setLoadedEvents((currentEvents) => mergeGraphEvents(currentEvents, page.events));
      setEventsPageInfo(page.page_info);
    } catch (error) {
      if (eventsRequestVersionRef.current !== requestVersion || currentTaskScopeIdRef.current !== requestTaskId) {
        return;
      }
      const message = error instanceof Error ? error.message : "加载更多关系变化失败";
      setEventsLoadError(message);
    } finally {
      if (eventsRequestVersionRef.current === requestVersion && currentTaskScopeIdRef.current === requestTaskId) {
        setIsEventsLoading(false);
      }
    }
  }, [eventsPageInfo, isEventsLoading, novelId, taskScopeId]);

  const handleGoTimeline = useCallback(() => {
    if (timelineUrl) {
      navigate(
        buildTimelineSelectionUrl(timelineUrl, {
          chunkId: selectedEvent?.chunk_id ?? initialSelectedChunk,
          relationEventId: selectedEvent?.relation_event_id,
        })
      );
    }
  }, [initialSelectedChunk, navigate, selectedEvent, timelineUrl]);

  const handleSelectEvent = useCallback((event: GraphEvent) => {
    // 中文注释：深链只负责首轮自动定位；用户手动改选后，应以当前交互为准，
    // 不能继续保留旧提示或在后续事件窗口刷新时强行拉回初始命中结果；
    // 同时要把当前选择同步回 URL，避免页面状态和 deep-link 语义继续分叉。
    setHasUserSelectedEvent(true);
    setSelectedEventId(event.relation_event_id);
    if (!novelId || !taskScopeId) {
      return;
    }
    navigate(
      buildGraphUrl(novelId, taskScopeId, {
        chunkId: event.chunk_id,
        relationEventId: event.relation_event_id,
      }),
      { replace: true }
    );
  }, [navigate, novelId, taskScopeId]);

  const handleOpenTimelineChunk = useCallback(
    (chunkId?: number, relationEventId?: number | null) => {
      if (!timelineUrl || chunkId == null) return;
      navigate(
        buildTimelineSelectionUrl(timelineUrl, {
          chunkId,
          relationEventId,
        })
      );
    },
    [navigate, timelineUrl]
  );

  const renderContractIssue = () => (
    <motion.section
      variants={pageSectionVariants}
      initial="hidden"
      animate="visible"
      transition={{ duration: 0.28, delay: 0.05 }}
    >
      <Card variant="elevated" className="rounded-2xl border-chart-negative/30">
        <CardContent className="flex flex-col gap-4 p-8">
          <div className="flex items-start gap-3">
            <AlertTriangle className="mt-0.5 h-6 w-6 text-chart-negative" />
            <div className="space-y-2">
              <p className="text-base font-semibold text-text">图谱数据暂不完整</p>
              <p className="text-sm leading-6 text-text-muted">
                当前任务返回了部分图谱数据，但关系概览或变化记录还不完整，请稍后重试。
              </p>
            </div>
          </div>
          <div className="flex flex-wrap gap-3">
            <Button variant="outline" size="sm" onClick={handleRetry}>
              <RefreshCw className="h-4 w-4" />
              重新请求
            </Button>
            <Button variant="outline" size="sm" onClick={handleGoTimeline} disabled={!timelineUrl}>
              打开时间轴
              <ArrowRight className="h-4 w-4" />
            </Button>
          </div>
        </CardContent>
      </Card>
    </motion.section>
  );

  const renderLoadedContent = () => (
    <>
      <motion.section
        variants={pageSectionVariants}
        initial="hidden"
        animate="visible"
        transition={{ duration: 0.28, delay: 0.05 }}
        className="grid gap-4 md:grid-cols-2 xl:grid-cols-4"
      >
        <MetricCard
          label="图谱实体"
          value={graphSummary?.node_count ?? 0}
          format="raw"
          decimals={0}
          icon={<Network className="h-5 w-5" />}
          description="当前识别到的人物、组织与群体"
          accent="primary"
        />
        <MetricCard
          label="关系连线"
          value={graphSummary?.edge_count ?? 0}
          format="raw"
          decimals={0}
          icon={<Link2 className="h-5 w-5" />}
          description="当前关系网络中的主要连接"
          accent="chart-2"
        />
        <MetricCard
          label="网络紧密度"
          value={graphSummary?.density ?? 0}
          format="raw"
          decimals={4}
          icon={<Activity className="h-5 w-5" />}
          description="角色之间连接的紧密程度"
          accent="chart-4"
        />
        <MetricCard
          label="关系变化"
          value={totalEventCount}
          format="raw"
          decimals={0}
          icon={<History className="h-5 w-5" />}
          description={
            totalEventCount > loadedEventCount
              ? `已加载 ${loadedEventCount} / ${totalEventCount} 条变化记录`
              : "已记录的关系变化"
          }
          accent="chart-5"
        />
      </motion.section>

      <motion.section
        variants={pageSectionVariants}
        initial="hidden"
        animate="visible"
        transition={{ duration: 0.28, delay: 0.1 }}
        className="grid gap-4 xl:grid-cols-3"
      >
        <DashboardCardShell
          title="核心网络"
          icon={<Users className="h-4 w-4" />}
          accent="primary"
          showOrb
          bodyClassName="gap-4"
        >
          <p className="text-sm text-text-muted">这一组角色处在当前关系网络的中心位置，适合作为阅读入口。</p>
          <div className="space-y-4 rounded-2xl border border-border/60 bg-surface/70 p-4">
            <div className="flex flex-wrap gap-2">
              {graphSummary?.core_characters.map((name) => (
                <Badge key={name} variant="secondary" className="px-3 py-1 text-sm">
                  {name}
                </Badge>
              ))}
            </div>
            <div className="rounded-xl border border-border/70 bg-surface-hover/40 p-4 text-sm text-text-muted">
              当前活跃关系 {activeRelationCount} 条
              {inactiveRelationCount > 0 ? `，另有 ${inactiveRelationCount} 条关系处于非活跃状态。` : "。"}
            </div>
          </div>
        </DashboardCardShell>

        <DashboardCardShell
          title="关键关系"
          icon={<Sparkles className="h-4 w-4" />}
          accent="chart-2"
          bodyClassName="gap-3"
        >
          <p className="text-sm text-text-muted">这里展示当前最重要、最能代表人物网络主干的关系。</p>
          <div className="space-y-3 rounded-2xl border border-border/60 bg-surface/70 p-4">
            {graphSummary?.key_relations.length ? (
              graphSummary.key_relations.map((relation) => (
                <div
                  key={`${relation.from}-${relation.to}-${relation.type ?? "unknown"}`}
                  className="rounded-xl border border-border/70 bg-surface-hover/40 p-4"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-sm font-medium text-text">
                        {relation.from} · {relation.to}
                      </p>
                      <p className="mt-1 text-xs text-text-muted">
                        {relation.type ?? "未标注关系类型"}
                      </p>
                    </div>
                    <Badge variant="outline">出现 {relation.support_count} 次</Badge>
                  </div>
                </div>
              ))
            ) : (
              <div className="rounded-xl border border-dashed border-border p-4 text-sm text-text-muted">
                暂无关键关系摘要。
              </div>
            )}
          </div>
        </DashboardCardShell>

        <DashboardCardShell
          title="边缘关系"
          icon={<AlertTriangle className="h-4 w-4 text-chart-negative" />}
          accent="chart-5"
          bodyClassName="gap-3"
        >
          <p className="text-sm text-text-muted">这些关系连接较弱或变化较少，更像是支线关系的补充信息。</p>
          <div className="space-y-3 rounded-2xl border border-border/60 bg-surface/70 p-4">
            {weakRelations.length ? (
              weakRelations.map((relation) => (
                <div
                  key={`${relation.source}-${relation.target}-${relation.relation_type ?? "unknown"}`}
                  className="rounded-xl border border-border/70 bg-surface-hover/40 p-4"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-sm font-medium text-text">
                        {relation.from} · {relation.to}
                      </p>
                      <p className="mt-1 text-xs text-text-muted">
                        {relation.relation_type ?? "未标注关系"}
                      </p>
                    </div>
                    <div className="text-right text-xs text-text-muted">
                      <div>连接强度 {relation.weight ?? 1}</div>
                      <div>变化 {relation.change_count ?? 0} 次</div>
                    </div>
                  </div>
                </div>
              ))
            ) : (
              <div className="rounded-xl border border-dashed border-border p-4 text-sm text-text-muted">
                当前没有明显的边缘关系。
              </div>
            )}
          </div>
        </DashboardCardShell>
      </motion.section>

      <motion.section
        variants={pageSectionVariants}
        initial="hidden"
        animate="visible"
        transition={{ duration: 0.28, delay: 0.15 }}
        className="grid gap-6 xl:grid-cols-[minmax(0,1.55fr),380px]"
      >
        <Card id="graph-workspace" variant="elevated" className="rounded-2xl">
          <CardHeader className="gap-4">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
              <div className="space-y-1">
                <CardTitle className="text-base">关系工作区</CardTitle>
                <CardDescription>
                  在这里可以缩放、筛选和定位人物之间的关系连接。
                </CardDescription>
              </div>
              <div className="overflow-x-auto pb-1">
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
                  className="w-max"
                />
              </div>
            </div>
          </CardHeader>

          <CardContent className="space-y-4">
            <div className="rounded-xl border border-border/70 bg-surface-hover/35 px-4 py-3 text-sm text-text-muted">
              可以先从上方的关系概览进入，再在这里放大、筛选并查看具体角色节点。
            </div>

            <div className="relative min-h-[620px] overflow-hidden rounded-xl border border-border bg-surface lg:min-h-[720px]">
              <ForceGraph
                ref={forceGraphRef}
                data={graphData!}
                onNodeClick={handleNodeClick}
                searchQuery={searchQuery}
                relationFilter={selectedRelationTypes}
                appearanceCountMap={appearanceCountMap}
                className="absolute inset-0"
              />

              <div className="absolute bottom-4 left-4 z-10 hidden md:block">
                <GraphLegend entityTypes={entityTypes} relationTypes={relationTypes} />
              </div>
            </div>
          </CardContent>
        </Card>

        <div className="space-y-4 xl:sticky xl:top-6 xl:self-start">
          <DashboardCardShell
            title="关系变化记录"
            icon={<History className="h-4 w-4" />}
            accent="chart-4"
            headerRight={
              <Badge variant="outline">
                {loadedEventCount < totalEventCount ? `${loadedEventCount} / ${totalEventCount}` : totalEventCount}
              </Badge>
            }
            footer={
              <Button variant="outline" size="sm" onClick={handleGoTimeline} disabled={!timelineUrl}>
                去时间轴联动查看
                <ArrowRight className="h-4 w-4" />
              </Button>
            }
            bodyClassName="gap-3"
          >
            <p className="text-sm text-text-muted">
              按剧情推进查看关系的建立、强化、弱化和断裂。
              {hasMoreEvents ? " 当前先展示一部分记录，可继续展开查看更多变化。" : ""}
            </p>
            <div className="space-y-3 rounded-2xl border border-border/60 bg-surface/70 p-4">
              {graphSelectionHint ? (
                <div className="rounded-xl border border-chart-negative/20 bg-chart-negative/5 p-3 text-xs leading-5 text-text-muted">
                  {graphSelectionHint}
                </div>
              ) : null}
              {sortedEvents.length ? (
                <>
                  <div className="max-h-[420px] space-y-3 overflow-y-auto pr-1">
                    {sortedEvents.map((event) => {
                      const isSelected = activeSelectedEventId === event.relation_event_id;
                      return (
                        <button
                          key={event.relation_event_id}
                          type="button"
                          onClick={() => handleSelectEvent(event)}
                          className={cn(
                            "w-full rounded-xl border p-4 text-left transition-colors",
                            isSelected
                              ? "border-primary/40 bg-primary/5"
                              : "border-border bg-surface hover:bg-surface-hover"
                          )}
                        >
                          <div className="flex items-start justify-between gap-3">
                            <div>
                              <p className="text-sm font-medium text-text">
                                第 {event.chunk_id} 段 · {event.from_name} → {event.to_name}
                              </p>
                              <p className="mt-1 text-xs leading-5 text-text-muted">
                                {event.relation_type ?? "未标注关系"} · {getChangeTypeLabel(event.change_type)}
                              </p>
                            </div>
                          </div>
                        </button>
                      );
                    })}
                  </div>

                  {(hasMoreEvents || isEventsLoading || eventsLoadError) && (
                    <div className="rounded-xl border border-border/70 bg-surface-hover/35 p-3">
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <p className="text-xs leading-5 text-text-muted">
                          {hasMoreEvents
                            ? `已加载 ${loadedEventCount} 条，仍有 ${Math.max(totalEventCount - loadedEventCount, 0)} 条变化可继续查看。`
                            : "变化记录已全部加载。"}
                        </p>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={handleLoadMoreEvents}
                          disabled={!hasMoreEvents || isEventsLoading}
                        >
                          {isEventsLoading ? "加载中..." : "加载更多"}
                        </Button>
                      </div>
                      {eventsLoadError ? (
                        <p className="mt-2 text-xs text-chart-negative">{eventsLoadError}</p>
                      ) : null}
                    </div>
                  )}
                </>
              ) : (
                <div className="rounded-xl border border-dashed border-border p-4 text-sm text-text-muted">
                  暂无关系变化记录。
                </div>
              )}
            </div>
          </DashboardCardShell>

          {selectedNode?.entity_type === "character" &&
          (selectedNode.first_seen_chunk != null || selectedNode.last_seen_chunk != null) ? (
            <DashboardCardShell
              title="角色生命周期联动"
              icon={<Users className="h-4 w-4" />}
              accent="chart-3"
              bodyClassName="gap-4"
          >
            <p className="text-sm text-text-muted">从这里可以继续查看角色在故事中的首次登场和最后活跃位置。</p>
              <div className="space-y-4 rounded-2xl border border-border/60 bg-surface/70 p-4">
                <div className="rounded-xl border border-border/70 bg-surface-hover/35 p-4 text-sm text-text-muted">
                  当前选中角色 <span className="font-medium text-text">{selectedNode.name}</span>
                  {selectedNode.first_seen_chunk != null && selectedNode.last_seen_chunk != null
                    ? `，稳定生命周期覆盖第 ${selectedNode.first_seen_chunk} 段到第 ${selectedNode.last_seen_chunk} 段。`
                    : "，可继续跳到时间轴查看稳定生命周期节点。"}
                </div>
                <div className="flex flex-wrap gap-3">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => handleOpenTimelineChunk(selectedNode.first_seen_chunk)}
                    disabled={selectedNode.first_seen_chunk == null || !timelineUrl}
                  >
                    查看首次登场
                    <ArrowRight className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => handleOpenTimelineChunk(selectedNode.last_seen_chunk)}
                    disabled={selectedNode.last_seen_chunk == null || !timelineUrl}
                  >
                    查看最后活跃
                    <ArrowRight className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            </DashboardCardShell>
          ) : null}

          <DashboardCardShell
            title="关系变化详情"
            icon={<Link2 className="h-4 w-4" />}
            accent="chart-2"
            bodyClassName="gap-3"
          >
            <p className="text-sm text-text-muted">查看当前选中关系变化的上下文说明和原文摘录。</p>
            <div className="rounded-2xl border border-border/60 bg-surface/70 p-4">
              {selectedEvent ? (
                <div className="space-y-4">
                  <div className="rounded-xl border border-border/70 bg-surface-hover/35 p-4">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="text-sm font-medium text-text">
                          第 {selectedEvent.chunk_id} 段 · {selectedEvent.from_name} → {selectedEvent.to_name}
                        </p>
                        <p className="mt-1 text-xs leading-5 text-text-muted">
                          {selectedEvent.relation_type ?? "未标注关系"} · {getChangeTypeLabel(selectedEvent.change_type)}
                        </p>
                      </div>
                    </div>
                  </div>

                  <div className="grid gap-3 sm:grid-cols-2">
                    <div className="rounded-xl border border-border bg-surface p-4">
                      <p className="text-xs uppercase tracking-wide text-text-muted">变化类型</p>
                      <p className="mt-2 text-sm font-medium text-text">{getChangeTypeLabel(selectedEvent.change_type)}</p>
                    </div>
                    <div className="rounded-xl border border-border bg-surface p-4">
                      <p className="text-xs uppercase tracking-wide text-text-muted">关系方向</p>
                      <p className="mt-2 text-sm font-medium text-text">{selectedEvent.directionality ?? "未声明"}</p>
                    </div>
                  </div>

                  <div className="rounded-xl border border-border bg-surface p-4">
                    <p className="text-xs uppercase tracking-wide text-text-muted">证据摘录</p>
                    <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-text">
                      {selectedEvent.evidence?.trim() || "当前事件没有附带 evidence 文本。"}
                    </p>
                  </div>
                </div>
              ) : (
                <div className="rounded-xl border border-dashed border-border p-6 text-center text-sm text-text-muted">
                  选择一条关系变化后，这里会显示详细上下文。
                </div>
              )}
            </div>
          </DashboardCardShell>
        </div>
      </motion.section>
    </>
  );

  // 中文注释：GraphPage 也需要和 TimelinePage 一样先兜住路由缺参空态，
  // 避免 novelId 缺失时继续渲染图谱分析入口，造成“页面存在但上下文不存在”的假象。
  if (!novelId) {
    return (
      <PageContainer>
        <div className="flex h-96 flex-col items-center justify-center gap-4">
          <div className="text-center">
            <h3 className="text-lg font-semibold text-text">小说不存在</h3>
            <p className="mt-1 text-sm text-text-muted">
              当前图谱入口缺少小说上下文，请从小说列表重新进入。
            </p>
          </div>
        </div>
      </PageContainer>
    );
  }

  if (!taskScopeId) {
    return (
      <PageContainer>
        <NovelHeader title={novelTitle} />
        <div className="flex h-96 flex-col items-center justify-center gap-4">
          <div className="text-center">
            <h3 className="text-lg font-semibold text-text">请先选择分析任务</h3>
            <p className="mt-1 text-sm text-text-muted">
              使用顶部任务选择器选择一个已完成的任务以查看图谱分析入口
            </p>
          </div>
        </div>
      </PageContainer>
    );
  }

  return (
    <PageContainer className="flex flex-col">
      <NovelHeader title={novelTitle} />

      <div className="mt-4 space-y-6">
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
        ) : graphContractIssue ? (
          renderContractIssue()
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
    </PageContainer>
  );
}

export default GraphPage;
