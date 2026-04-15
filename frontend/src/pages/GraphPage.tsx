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
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Users,
} from "lucide-react";
import { getCharacters, getGraph, getGraphEvents } from "@/api/results";
import { getNovel } from "@/api/novels";
import { useNovelStore } from "@/store/novelStore";
import { cn } from "@/lib/cn";
import { PageContainer } from "@/components/layout/PageContainer";
import { NovelHeader } from "@/components/common/NovelHeader";
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
const LOW_CONFIDENCE_THRESHOLD = 0.6;

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

function buildTimelineUrl(novelId: string, taskId: string): string {
  return `/novels/${novelId}/timeline?task_id=${taskId}&max_level=3&show_tension=true`;
}

function formatDensity(value: number | undefined): string {
  if (value == null || Number.isNaN(value)) return "--";
  return value.toFixed(4);
}

function formatConfidence(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "待确认";
  return `${Math.round(value * 100)}%`;
}

function getChangeTypeLabel(changeType?: string | null): string {
  if (!changeType) return "变化";
  return changeTypeLabels[changeType] ?? changeType;
}

function getEventConfidenceVariant(confidence: number | null | undefined): "outline" | "success" | "destructive" {
  if (confidence == null) return "outline";
  if (confidence < LOW_CONFIDENCE_THRESHOLD) return "destructive";
  return "success";
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
  const { currentTaskId, setNovel, setTask } = useNovelStore();

  const urlTaskId = searchParams.get("task_id");
  const forceGraphRef = useRef<ForceGraphHandle>(null);

  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedRelationTypes, setSelectedRelationTypes] = useState<Set<string>>(new Set());
  const [isPanelOpen, setIsPanelOpen] = useState(false);
  const [selectedEventId, setSelectedEventId] = useState<number | null>(null);
  const [loadedEvents, setLoadedEvents] = useState<GraphEvent[]>([]);
  const [eventsPageInfo, setEventsPageInfo] = useState<GraphEventsPageInfo | null>(null);
  const [isEventsLoading, setIsEventsLoading] = useState(false);
  const [eventsLoadError, setEventsLoadError] = useState<string | null>(null);

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

  const charactersQuery = useQuery({
    queryKey: ["characters", novelId, currentTaskId],
    queryFn: () => getCharacters(novelId!, currentTaskId!),
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
  const graphContractIssue = enabled && !!graphData && (!graphData.summary || !graphData.quality || !graphData.events_page);

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
  const graphQuality = graphData?.quality ?? null;

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

  const selectedEvent = useMemo(() => {
    if (sortedEvents.length === 0) return null;
    if (selectedEventId == null) return sortedEvents[0];
    return sortedEvents.find((event) => event.relation_event_id === selectedEventId) ?? sortedEvents[0];
  }, [sortedEvents, selectedEventId]);
  const activeSelectedEventId = selectedEvent?.relation_event_id ?? null;

  useEffect(() => {
    setLoadedEvents(graphData?.events ?? []);
    setEventsPageInfo(graphData?.events_page ?? null);
    setEventsLoadError(null);
    setIsEventsLoading(false);
  }, [graphData]);

  useEffect(() => {
    setSelectedNode(null);
    setIsPanelOpen(false);
    setSelectedEventId(null);
  }, [currentTaskId, graphQuery.dataUpdatedAt]);

  useEffect(() => {
    if (!graphContractIssue || !graphData) return;

    const missingFields = [
      graphData.summary ? null : "summary",
      graphData.quality ? null : "quality",
      graphData.events_page ? null : "events_page",
    ].filter(Boolean);

    console.error("[GraphPage] /graph authority contract is missing required fields:", {
      taskId: currentTaskId,
      missingFields,
    });
  }, [currentTaskId, graphContractIssue, graphData]);

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

  const qualityTone = useMemo(() => {
    if (!graphQuality) {
      return {
        icon: ShieldCheck,
        badgeVariant: "outline" as const,
        badgeLabel: "待评估",
        summary: "等待 authority 质量报告。",
      };
    }
    if (graphQuality.conflict_count === 0 && graphQuality.low_confidence_count === 0) {
      return {
        icon: ShieldCheck,
        badgeVariant: "success" as const,
        badgeLabel: "稳定",
        summary: "当前 authority 输出没有显著冲突，可直接支撑更高层分析。",
      };
    }
    return {
      icon: ShieldAlert,
      badgeVariant: "destructive" as const,
      badgeLabel: "需关注",
      summary: "建议先处理冲突关系与低置信事件，再继续做诊断或聚合分析。",
    };
  }, [graphQuality]);

  const timelineUrl = novelId && currentTaskId ? buildTimelineUrl(novelId, currentTaskId) : null;
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
    if (!novelId || !currentTaskId || !eventsPageInfo?.next_cursor || isEventsLoading) {
      return;
    }

    setIsEventsLoading(true);
    setEventsLoadError(null);
    try {
      const page = await getGraphEvents(novelId, currentTaskId, {
        eventsCursor: eventsPageInfo.next_cursor,
        eventsLimit: eventsPageInfo.limit,
      });
      setLoadedEvents((currentEvents) => mergeGraphEvents(currentEvents, page.events));
      setEventsPageInfo(page.page_info);
    } catch (error) {
      const message = error instanceof Error ? error.message : "加载更多 relation events 失败";
      setEventsLoadError(message);
    } finally {
      setIsEventsLoading(false);
    }
  }, [currentTaskId, eventsPageInfo, isEventsLoading, novelId]);

  const handleGoTimeline = useCallback(() => {
    if (timelineUrl) {
      const chunkParam = selectedEvent?.chunk_id != null ? `&selected_chunk=${selectedEvent.chunk_id}` : "";
      const eventParam =
        selectedEvent?.relation_event_id != null ? `&relation_event_id=${selectedEvent.relation_event_id}` : "";
      navigate(`${timelineUrl}${chunkParam}${eventParam}`);
    }
  }, [navigate, selectedEvent, timelineUrl]);

  const handleScrollToGraph = useCallback(() => {
    const graphSection = document.getElementById("graph-workspace");
    graphSection?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, []);

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
              <p className="text-base font-semibold text-text">/graph authority contract 不完整</p>
              <p className="text-sm leading-6 text-text-muted">
                当前任务返回了图数据，但缺少 `summary`、`quality` 或 `events_page`。图谱分析入口不会在前端补造
                authority 语义，请先修复后端 contract 再继续使用该页面。
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
          description="authority 当前稳定实体数"
          accent="primary"
        />
        <MetricCard
          label="确认关系"
          value={graphSummary?.edge_count ?? 0}
          format="raw"
          decimals={0}
          icon={<Link2 className="h-5 w-5" />}
          description="当前确认后的关系边数"
          accent="chart-2"
        />
        <MetricCard
          label="网络密度"
          value={graphSummary?.density ?? 0}
          format="raw"
          decimals={4}
          icon={<Activity className="h-5 w-5" />}
          description="关系连接紧密度"
          accent="chart-4"
        />
        <MetricCard
          label="历史事件"
          value={totalEventCount}
          format="raw"
          decimals={0}
          icon={<History className="h-5 w-5" />}
          description={
            totalEventCount > loadedEventCount
              ? `已加载 ${loadedEventCount} / ${totalEventCount} 条 history`
              : "relation events 历史条目"
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
        <Card variant="elevated" className="rounded-2xl">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Users className="h-4 w-4 text-primary" />
              核心网络
            </CardTitle>
            <CardDescription>summary 里当前最值得先读的核心角色集合。</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
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
          </CardContent>
        </Card>

        <Card variant="elevated" className="rounded-2xl">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Sparkles className="h-4 w-4 text-primary" />
              关键关系
            </CardTitle>
            <CardDescription>按 summary.support_count 排序，优先看最能代表主干结构的关系。</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
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
                    <Badge variant="outline">支撑 {relation.support_count}</Badge>
                  </div>
                </div>
              ))
            ) : (
              <div className="rounded-xl border border-dashed border-border p-4 text-sm text-text-muted">
                暂无关键关系摘要。
              </div>
            )}
          </CardContent>
        </Card>

        <Card variant="elevated" className="rounded-2xl">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <AlertTriangle className="h-4 w-4 text-chart-negative" />
              弱连接候选
            </CardTitle>
            <CardDescription>基于当前边权重和变化次数，优先暴露需要二次确认的边缘连接。</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
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
                      <div>权重 {relation.weight ?? 1}</div>
                      <div>变更 {relation.change_count ?? 0}</div>
                    </div>
                  </div>
                </div>
              ))
            ) : (
              <div className="rounded-xl border border-dashed border-border p-4 text-sm text-text-muted">
                当前没有足够的边数据来识别弱连接。
              </div>
            )}
          </CardContent>
        </Card>
      </motion.section>

      <motion.section
        variants={pageSectionVariants}
        initial="hidden"
        animate="visible"
        transition={{ duration: 0.28, delay: 0.15 }}
      >
        <Card variant="elevated" className="rounded-2xl">
          <CardHeader className="gap-3">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
              <div>
                <CardTitle className="flex items-center gap-2 text-base">
                  <qualityTone.icon className="h-4 w-4 text-primary" />
                  Authority 质量诊断
                </CardTitle>
                <CardDescription className="mt-1">
                  quality 只反映 authority 输出稳定性，不直接等于诊断页的高层结论。
                </CardDescription>
              </div>
              <Badge variant={qualityTone.badgeVariant}>{qualityTone.badgeLabel}</Badge>
            </div>
            <p className="text-sm text-text-muted">{qualityTone.summary}</p>
          </CardHeader>

          <CardContent className="grid gap-4 xl:grid-cols-[280px,minmax(0,1fr),minmax(0,1fr)]">
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-1">
              <MetricCard
                label="冲突关系"
                value={graphQuality?.conflict_count ?? 0}
                format="raw"
                decimals={0}
                icon={<ShieldAlert className="h-5 w-5" />}
                description="同一实体对出现多个关系类型"
                accent="chart-3"
              />
              <MetricCard
                label="低置信事件"
                value={graphQuality?.low_confidence_count ?? 0}
                format="raw"
                decimals={0}
                icon={<AlertTriangle className="h-5 w-5" />}
                description={`置信度低于 ${Math.round(LOW_CONFIDENCE_THRESHOLD * 100)}% 的历史变化`}
                accent="chart-5"
              />
            </div>

            <div className="rounded-2xl border border-border/70 bg-surface-hover/35 p-4">
              <div className="mb-3 flex items-center justify-between gap-3">
                <h3 className="text-sm font-semibold text-text">冲突样本</h3>
                <Badge variant="outline">{graphQuality?.conflicts.length ?? 0} 条样本</Badge>
              </div>
              <div className="space-y-3">
                {graphQuality?.conflicts.length ? (
                  graphQuality.conflicts.map((conflict) => (
                    <div
                      key={`${conflict.entity_names.join("-")}-${conflict.relation_types.join("-")}`}
                      className="rounded-xl border border-border bg-surface p-4"
                    >
                      <p className="text-sm font-medium text-text">{conflict.entity_names.join(" · ")}</p>
                      <p className="mt-1 text-xs leading-5 text-text-muted">
                        关系类型: {conflict.relation_types.join(" / ")}
                      </p>
                      <p className="mt-1 text-xs text-text-muted">
                        冲突关系数 {conflict.relation_count}，最近事件 ID: {conflict.latest_event_ids.join(", ") || "无"}
                      </p>
                    </div>
                  ))
                ) : (
                  <div className="flex h-full min-h-40 flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border bg-surface p-4 text-center">
                    <ShieldCheck className="h-8 w-8 text-chart-positive" />
                    <p className="text-sm font-medium text-text">当前没有冲突关系</p>
                    <p className="text-xs text-text-muted">实体对之间的关系类型保持一致。</p>
                  </div>
                )}
              </div>
            </div>

            <div className="rounded-2xl border border-border/70 bg-surface-hover/35 p-4">
              <div className="mb-3 flex items-center justify-between gap-3">
                <h3 className="text-sm font-semibold text-text">低置信事件</h3>
                <Badge variant="outline">{graphQuality?.low_confidence_samples.length ?? 0} 条样本</Badge>
              </div>
              <div className="space-y-3">
                {graphQuality?.low_confidence_samples.length ? (
                  graphQuality.low_confidence_samples.map((event) => (
                    <div
                      key={event.relation_event_id}
                      className="rounded-xl border border-border bg-surface p-4"
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
                        <Badge variant={getEventConfidenceVariant(event.confidence)}>
                          {formatConfidence(event.confidence)}
                        </Badge>
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="flex h-full min-h-40 flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border bg-surface p-4 text-center">
                    <ShieldCheck className="h-8 w-8 text-chart-positive" />
                    <p className="text-sm font-medium text-text">没有低置信事件</p>
                    <p className="text-xs text-text-muted">历史关系变化的可信度目前处于健康区间。</p>
                  </div>
                )}
              </div>
            </div>
          </CardContent>
        </Card>
      </motion.section>

      <motion.section
        variants={pageSectionVariants}
        initial="hidden"
        animate="visible"
        transition={{ duration: 0.28, delay: 0.2 }}
        className="grid gap-6 xl:grid-cols-[minmax(0,1.55fr),380px]"
      >
        <Card id="graph-workspace" variant="elevated" className="rounded-2xl">
          <CardHeader className="gap-4">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
              <div className="space-y-1">
                <CardTitle className="text-base">关系工作区</CardTitle>
                <CardDescription>
                  关系图仍然保留，但它现在服务于 summary / quality / events 的分析流程。
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
              先用上方 summary 和 quality 缩小问题范围，再在关系图里放大、筛选和定位具体节点。
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
          <Card variant="elevated" className="rounded-2xl">
            <CardHeader className="gap-3">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <CardTitle className="flex items-center gap-2 text-base">
                    <History className="h-4 w-4 text-primary" />
                    历史变化入口
                  </CardTitle>
                  <CardDescription className="mt-1">
                    events 侧栏直接承接 relation history，不再只靠时间轴页兜底。
                    {hasMoreEvents ? " 当前只首屏加载样本，可继续增量展开更长历史。" : ""}
                  </CardDescription>
                </div>
                <Badge variant="outline">
                  {loadedEventCount < totalEventCount ? `${loadedEventCount} / ${totalEventCount}` : totalEventCount}
                </Badge>
              </div>
              <Button variant="outline" size="sm" onClick={handleGoTimeline} disabled={!timelineUrl}>
                去时间轴联动查看
                <ArrowRight className="h-4 w-4" />
              </Button>
            </CardHeader>

            <CardContent className="space-y-3">
              {sortedEvents.length ? (
                <>
                  <div className="max-h-[420px] space-y-3 overflow-y-auto pr-1">
                    {sortedEvents.map((event) => {
                      const isSelected = activeSelectedEventId === event.relation_event_id;
                      return (
                        <button
                          key={event.relation_event_id}
                          type="button"
                          onClick={() => setSelectedEventId(event.relation_event_id)}
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
                            <Badge variant={getEventConfidenceVariant(event.confidence)}>
                              {formatConfidence(event.confidence)}
                            </Badge>
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
                            ? `已加载 ${loadedEventCount} 条，仍有 ${Math.max(totalEventCount - loadedEventCount, 0)} 条历史可继续查看。`
                            : "历史样本已全部加载。"}
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
                  暂无 relation events 历史。
                </div>
              )}
            </CardContent>
          </Card>

          <Card variant="elevated" className="rounded-2xl">
            <CardHeader>
              <CardTitle className="text-base">事件详情</CardTitle>
              <CardDescription>查看选中历史变化的证据、方向和质量信息。</CardDescription>
            </CardHeader>
            <CardContent>
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
                      <Badge variant={getEventConfidenceVariant(selectedEvent.confidence)}>
                        {formatConfidence(selectedEvent.confidence)}
                      </Badge>
                    </div>
                  </div>

                  <div className="grid gap-3 sm:grid-cols-2">
                    <div className="rounded-xl border border-border bg-surface p-4">
                      <p className="text-xs uppercase tracking-wide text-text-muted">方向性</p>
                      <p className="mt-2 text-sm font-medium text-text">{selectedEvent.directionality ?? "未声明"}</p>
                    </div>
                    <div className="rounded-xl border border-border bg-surface p-4">
                      <p className="text-xs uppercase tracking-wide text-text-muted">事件 ID</p>
                      <p className="mt-2 text-sm font-medium text-text">{selectedEvent.relation_event_id}</p>
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
                  选择一条历史事件后，这里会显示详细上下文。
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </motion.section>
    </>
  );

  if (!currentTaskId) {
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
        <motion.section
          variants={pageSectionVariants}
          initial="hidden"
          animate="visible"
          transition={{ duration: 0.28 }}
        >
          <Card
            variant="elevated"
            className="overflow-hidden rounded-2xl border-border bg-gradient-to-br from-surface via-surface to-primary/10"
          >
            <CardContent className="flex flex-col gap-6 p-6 lg:flex-row lg:items-end lg:justify-between">
              <div className="max-w-3xl space-y-4">
                <div className="inline-flex items-center gap-2 rounded-full border border-primary/20 bg-primary/10 px-3 py-1 text-xs font-medium text-primary">
                  <Sparkles className="h-3.5 w-3.5" />
                  Graph Product Surface · 第一轮迁移
                </div>

                <div className="space-y-2">
                  <h2 className="text-2xl font-semibold tracking-tight text-text">
                    先读图谱 summary，再检查 quality，最后沿着 events 进入历史变化
                  </h2>
                  <p className="max-w-2xl text-sm leading-6 text-text-muted">
                    这页现在不只展示关系图，而是把 authority 层已经产出的 summary、quality 和 relation
                    events 直接变成产品入口，帮助我们更快判断核心网络、风险点与关系演化路径。
                  </p>
                </div>

                {!isLoading && !isError && !isEmpty && graphSummary && (
                  <div className="flex flex-wrap gap-2">
                    <Badge variant="secondary">{graphSummary.node_count} 个实体</Badge>
                    <Badge variant="secondary">{graphSummary.edge_count} 条关系</Badge>
                    <Badge variant="outline">密度 {formatDensity(graphSummary.density)}</Badge>
                    <Badge variant={qualityTone.badgeVariant}>{qualityTone.badgeLabel}</Badge>
                  </div>
                )}
              </div>

              <div className="flex flex-wrap gap-3">
                <Button onClick={handleGoTimeline} disabled={!timelineUrl}>
                  查看历史时间轴
                  <ArrowRight className="h-4 w-4" />
                </Button>
                <Button
                  variant="outline"
                  onClick={handleScrollToGraph}
                  disabled={isLoading || isError || isEmpty}
                >
                  进入关系工作区
                </Button>
              </div>
            </CardContent>
          </Card>
        </motion.section>

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
                    <p className="text-sm font-medium text-text">正在加载图谱 authority 输出</p>
                    <p className="text-sm text-text-muted">页面会按 summary → quality → events 的顺序展开。</p>
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
                  <p className="text-base font-semibold text-text">该任务尚未产生图谱 authority 输出</p>
                  <p className="text-sm text-text-muted">完成图谱投影后，这里会自动显示 summary、quality 与事件历史。</p>
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
