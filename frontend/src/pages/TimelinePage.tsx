/**
 * 2026-08-20，作用：展示事件森林时间轴页面
 * 简要说明：一棵事件树对应一个轨道节点，点击节点就地悬浮展示详情
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams, useSearchParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, RefreshCw } from "lucide-react";
import { getTimeline } from "@/api/results";
import { getNovel } from "@/api/novels";
import { isAnalysisNotCompleteError, getAnalysisNotCompleteRunStatus } from "@/api/errorGuards";
import { useNovelStore } from "@/store/novelStore";
import { AnalysisWorkspace } from "@/components/layout/AnalysisWorkspace";
import { AnalysisNotCompleteState } from "@/components/common/AnalysisNotCompleteState";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { TimelineEventPopover } from "@/components/timeline/TimelineEventPopover";
import {
  TimelineLegend,
  TimelineTrack,
  TimelineEventInspector,
  TimelineControls,
} from "@/components/timeline";
import type { EventTimelineResponse, TimelineEventNode } from "@/api/types";
import { buildGraphUrl } from "@/pages/graph/graphPageNavigation";

const STALE_TIME = 5 * 60 * 1000;

function buildTimelinePageUrl(
  novelId: string,
  taskId: string,
  options: {
    maxLevel?: 1 | 2 | 3;
    treeId?: string | null;
    eventId?: string | null;
  }
): string {
  const params = new URLSearchParams({
    task_id: taskId,
  });
  if (options.maxLevel != null) {
    params.set("max_level", String(options.maxLevel));
  }
  if (options.treeId) {
    params.set("tree_id", options.treeId);
  }
  if (options.eventId) {
    params.set("event_id", options.eventId);
  }
  return `/novels/${novelId}/timeline?${params.toString()}`;
}

export function TimelinePage() {
  const { novelId } = useParams<{ novelId: string }>();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { currentNovelId, currentTaskId, setNovel, setTask } = useNovelStore();

  const urlTaskId = searchParams.get("task_id");
  const urlMaxLevel = searchParams.get("max_level");
  const urlTreeId = searchParams.get("tree_id");
  const urlEventId = searchParams.get("event_id");
  const urlTaskSyncRef = useRef<string | null>(urlTaskId && currentTaskId !== urlTaskId ? urlTaskId : null);

  const maxLevel = useMemo<1 | 2 | 3>(() => {
    const level = urlMaxLevel ? parseInt(urlMaxLevel, 10) : 3;
    return [1, 2, 3].includes(level) ? (level as 1 | 2 | 3) : 3;
  }, [urlMaxLevel]);

  const [activePhase, setActivePhase] = useState<string | undefined>();
  const [anchor, setAnchor] = useState<{ treeId: string; element: HTMLElement } | null>(null);
  const storeTaskId = currentNovelId === novelId ? currentTaskId : null;
  const taskScopeId = urlTaskId ?? storeTaskId;

  useEffect(() => {
    if (novelId) {
      setNovel(novelId);
      if (urlTaskId) {
        const currentStoreState = useNovelStore.getState();
        const currentStoreTaskId =
          currentStoreState.currentNovelId === novelId ? currentStoreState.currentTaskId : null;
        if (currentStoreTaskId !== urlTaskId) {
          urlTaskSyncRef.current = urlTaskId;
        }
        setTask(urlTaskId);
      }
    }
  }, [novelId, setNovel, setTask, urlTaskId]);

  useEffect(() => {
    if (!novelId || !storeTaskId) return;
    if (urlTaskId === storeTaskId) {
      if (urlTaskSyncRef.current === storeTaskId) urlTaskSyncRef.current = null;
      return;
    }
    if (urlTaskId && urlTaskSyncRef.current === urlTaskId) return;

    navigate(
      buildTimelinePageUrl(novelId, storeTaskId, {
        maxLevel,
        treeId: null,
        eventId: null,
      }),
      { replace: true }
    );
  }, [maxLevel, navigate, novelId, storeTaskId, urlTaskId]);

  const enabled = !!novelId && !!taskScopeId;

  const timelineQuery = useQuery<EventTimelineResponse>({
    queryKey: ["timeline", novelId, taskScopeId],
    queryFn: () => getTimeline(novelId!, taskScopeId!, { includeCurve: true }),
    enabled,
    staleTime: STALE_TIME,
  });

  const novelQuery = useQuery({
    queryKey: ["novel", novelId],
    queryFn: () => getNovel(novelId!),
    enabled: !!novelId,
    staleTime: STALE_TIME,
  });

  const timelineData = timelineQuery.data;
  const phases = timelineData?.phases ?? [];
  const nodes: TimelineEventNode[] = useMemo(() => timelineData?.nodes ?? [], [timelineData?.nodes]);
  const causalEdges = useMemo(() => timelineData?.causal_edges ?? [], [timelineData?.causal_edges]);
  const foreshadowingEdges = useMemo(() => timelineData?.foreshadowing_edges ?? [], [timelineData?.foreshadowing_edges]);
  const derivedOrder = useMemo(() => timelineData?.derived_event_order ?? [], [timelineData?.derived_event_order]);
  const tensionCurve = timelineData?.tension_curve;
  const totalChapters = timelineData?.meta?.total_chapters ?? timelineData?.total_chapters ?? 0;

  const displayNodes = useMemo(() => {
    if (nodes.length === 0) return [];
    const orderIndex = new Map(derivedOrder.map((id, idx) => [id, idx] as const));
    // 树按 derivedOrder 排序：优先匹配 tree_id，其次 root_event_id，再按 progress 兜底
    const sorted = [...nodes].sort((a, b) => {
      const aIdx = orderIndex.get(a.tree_id) ?? orderIndex.get(a.root_event_id) ?? null;
      const bIdx = orderIndex.get(b.tree_id) ?? orderIndex.get(b.root_event_id) ?? null;
      if (aIdx != null && bIdx != null) return aIdx - bIdx;
      if (aIdx != null) return -1;
      if (bIdx != null) return 1;
      return a.progress - b.progress;
    });
    // 按 level 统一过滤（importance_score 已分位数映射到 level）
    return sorted.filter((n) => n.level <= maxLevel);
  }, [nodes, derivedOrder, maxLevel]);
  const selectedDetailNode = useMemo<TimelineEventNode | null>(() => {
    if (nodes.length === 0) return null;
    if (urlTreeId) {
      const byTree = nodes.find((n) => n.tree_id === urlTreeId);
      if (byTree) return byTree;
    }
    if (urlEventId) {
      const byEvent = nodes.find((n) =>
        n.root_event_id === urlEventId || n.main_chain.includes(urlEventId) || n.tree_id === urlEventId ||
        n.secondary_groups.some((group) => group.target_event_id === urlEventId || group.branch.includes(urlEventId))
      );
      if (byEvent) return byEvent;
    }
    return null;
  }, [nodes, urlTreeId, urlEventId]);

  const selectionHint = useMemo(() => {
    if (!urlTreeId && !urlEventId) return null;
    if (selectedDetailNode) return null;
    if (urlTreeId || urlEventId) return "未找到链接指向的事件，已保留当前时间轴内容";
    return null;
  }, [selectedDetailNode, urlEventId, urlTreeId]);

  const selectedTrackNodeId = selectedDetailNode?.root_event_id;

  const eventCount = nodes.length;
  const causalCount = causalEdges.length;
  const visibleCount = displayNodes.length;

  const handleMaxLevelChange = useCallback(
    (level: 1 | 2 | 3) => {
      if (!novelId || !taskScopeId) return;
      setAnchor(null);
      navigate(
        buildTimelinePageUrl(novelId, taskScopeId, {
          maxLevel: level,
          treeId: selectedDetailNode?.tree_id ?? urlTreeId,
          eventId: selectedDetailNode?.root_event_id ?? urlEventId,
        }),
        { replace: true }
      );
    },
    [novelId, taskScopeId, navigate, selectedDetailNode, urlEventId, urlTreeId]
  );

  const handleNodeClick = useCallback(
    (node: TimelineEventNode, card: HTMLElement) => {
      if (!novelId || !taskScopeId) return;
      const isSameNode = selectedDetailNode?.tree_id === node.tree_id;
      setAnchor(isSameNode ? null : { treeId: node.tree_id, element: card });
      navigate(
        buildTimelinePageUrl(novelId, taskScopeId, {
          maxLevel,
          treeId: isSameNode ? null : node.tree_id,
          eventId: isSameNode ? null : node.root_event_id,
        }),
        { replace: true }
      );
    },
    [maxLevel, navigate, novelId, selectedDetailNode, taskScopeId]
  );

  const handleSelectChapter = useCallback(
    (chapterId: number) => {
      if (!novelId || !taskScopeId) return;
      navigate(buildGraphUrl(novelId, taskScopeId, { chapterId }));
    },
    [navigate, novelId, taskScopeId]
  );

  const handleSelectTree = useCallback(
    (treeId: string) => {
      if (!novelId || !taskScopeId) return;
      // treeId 可能是 event_id，外层会按 event_id 回退查找
      const targetNode = nodes.find((n) => n.tree_id === treeId || n.root_event_id === treeId || n.main_chain.includes(treeId));
      const resolvedTreeId = targetNode?.tree_id ?? treeId;
      setAnchor(null);
      navigate(
        buildTimelinePageUrl(novelId, taskScopeId, {
          maxLevel,
          treeId: resolvedTreeId,
          eventId: targetNode?.root_event_id ?? null,
        }),
        { replace: true }
      );
    },
    [maxLevel, navigate, nodes, novelId, taskScopeId]
  );

  const handleRetry = useCallback(() => {
    timelineQuery.refetch();
  }, [timelineQuery]);

  const handleCloseDetail = useCallback(() => {
    if (!novelId || !taskScopeId) return;
    setAnchor(null);
    navigate(buildTimelinePageUrl(novelId, taskScopeId, { maxLevel, treeId: null, eventId: null }), { replace: true });
  }, [maxLevel, navigate, novelId, taskScopeId]);

  const isLoading = timelineQuery.isLoading || novelQuery.isLoading;
  const isAnalysisNotComplete = isAnalysisNotCompleteError(timelineQuery.error);
  const analysisFailed = getAnalysisNotCompleteRunStatus(timelineQuery.error) === "failed";
  const isError = (timelineQuery.isError || novelQuery.isError) && !isAnalysisNotComplete;

  if (!novelId) {
    return (
      <AnalysisWorkspace title="叙事时间轴">
        <div className="flex h-96 flex-col items-center justify-center gap-4">
          <div className="text-center">
            <h3 className="text-lg font-semibold text-text">小说不存在</h3>
            <p className="mt-1 text-sm text-text-muted">请从小说列表中选择一本小说</p>
          </div>
        </div>
      </AnalysisWorkspace>
    );
  }

  if (!taskScopeId) {
    return (
      <AnalysisWorkspace title="叙事时间轴">
        <div className="flex h-96 flex-col items-center justify-center gap-4">
          <div className="text-center">
            <h3 className="text-lg font-semibold text-text">请先选择分析任务</h3>
            <p className="mt-1 text-sm text-text-muted">使用顶部任务选择器选择一个已完成的任务以查看时间轴</p>
          </div>
        </div>
      </AnalysisWorkspace>
    );
  }

  return (
    <AnalysisWorkspace title="叙事时间轴">
      <div className="flex h-full min-h-0 flex-col">
        {isLoading ? (
          <div className="h-full w-full animate-pulse rounded-lg border border-border/60 bg-surface-hover" />
        ) : isAnalysisNotComplete ? (
          <AnalysisNotCompleteState
            title={analysisFailed ? "时间轴分析任务已失败" : "时间轴结果尚未完成"}
            description={
              analysisFailed
                ? "该分析任务已失败，时间轴数据无法读取，请重新发起分析后再查看。"
                : "当前任务仍在分析中，时间轴数据暂时不可读，请等待任务进入完成态后再查看。"
            }
            failed={analysisFailed}
          />
        ) : isError ? (
          <div className="flex h-full flex-col items-center justify-center gap-3 rounded-lg border border-border/60 bg-surface/70 text-sm text-text-muted">
            <span>时间轴加载失败</span>
            <Button variant="outline" size="sm" onClick={handleRetry} className="gap-2">
              <RefreshCw className="h-4 w-4" aria-hidden="true" />
              重试
            </Button>
          </div>
        ) : nodes.length === 0 && totalChapters === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-3 rounded-lg border border-border/60 bg-surface/70 text-sm text-text-muted">
            <span>该任务没有事件时间轴数据，请重新分析</span>
            <Button variant="outline" size="sm" onClick={() => navigate(`/novels/${novelId}`)} className="gap-2">
              <RefreshCw className="h-4 w-4" aria-hidden="true" />
              重新分析
            </Button>
          </div>
        ) : nodes.length === 0 || displayNodes.length === 0 ? (
          <div className="flex h-full items-center justify-center rounded-lg border border-border/60 bg-surface/70 text-sm text-text-muted">
            暂无时间轴节点
          </div>
        ) : (
          <div className="flex h-full min-h-0 flex-col gap-2">
            <dl className="grid shrink-0 grid-cols-3 gap-2" aria-label="事件轨道摘要">
              {[
                ["事件总数", eventCount], ["当前可见", visibleCount], ["因果联系", causalCount],
              ].map(([label, value]) => (
                <div key={label} className="flex items-center justify-between rounded-lg border border-border/70 bg-surface/75 px-3 py-1 text-xs">
                  <dt className="text-text-muted">{label}</dt>
                  <dd className="font-semibold tabular-nums text-text">{value}</dd>
                </div>
              ))}
            </dl>
            <div className="flex shrink-0 items-center gap-2" aria-label="时间轴筛选">
              <TimelineControls variant="inline" maxLevel={maxLevel} onMaxLevelChange={handleMaxLevelChange} className="min-w-0 flex-1" />
              <Select value={activePhase ?? "all"} onValueChange={(value) => setActivePhase(value === "all" ? undefined : value)}>
                <SelectTrigger className="w-48 shrink-0" aria-label="叙事阶段筛选"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">全部阶段</SelectItem>
                  {phases.map((phase) => <SelectItem key={phase.name} value={phase.name}>{phase.name} · 第 {phase.start} 至 {phase.end} 章</SelectItem>)}
                </SelectContent>
              </Select>
              <details className="relative z-20 shrink-0">
                <summary className="cursor-pointer list-none rounded-lg border border-border/70 bg-surface px-3 py-2 text-xs text-text">图例</summary>
                <div className="absolute right-0 top-full mt-2 w-[580px] rounded-xl border border-border/70 bg-background p-3 shadow-lg">
                  <TimelineLegend />
                </div>
              </details>
            </div>
            {selectionHint && <p className="flex items-center gap-2 text-xs text-text-muted">
              <AlertTriangle className="h-4 w-4 text-chart-negative" aria-hidden="true" />{selectionHint}
            </p>}
            <section className="min-h-0 flex-1" aria-label="事件轨道">
              <TimelineTrack
                nodes={displayNodes}
                derivedOrder={derivedOrder}
                phases={phases}
                activePhase={activePhase}
                selectedNodeId={selectedTrackNodeId}
                onNodeClick={handleNodeClick}
                tensionCurve={tensionCurve ?? null}
                totalChapters={totalChapters}
                className="h-full min-h-0"
              />
            </section>
          </div>
        )}
      </div>
      {selectedDetailNode && <TimelineEventPopover
        anchor={anchor?.treeId === selectedDetailNode.tree_id ? anchor.element : null}
        onClose={handleCloseDetail}
      >
        <TimelineEventInspector
          node={selectedDetailNode}
          nodes={nodes}
          novelId={novelId}
          taskId={taskScopeId}
          causalEdges={causalEdges}
          foreshadowingEdges={foreshadowingEdges}
          onClose={handleCloseDetail}
          onSelectChapter={handleSelectChapter}
          onSelectTree={handleSelectTree}
          className="h-full"
        />
      </TimelineEventPopover>}
    </AnalysisWorkspace>
  );
}
