/** 2026-08-20 事件森林一树一节点版：不兼容旧 composite/atomic 接口 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams, useSearchParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, GitBranch, RefreshCw, Sparkles } from "lucide-react";
import { getTimeline } from "@/api/results";
import { getNovel } from "@/api/novels";
import { isAnalysisNotCompleteError, getAnalysisNotCompleteRunStatus } from "@/api/errorGuards";
import { useNovelStore } from "@/store/novelStore";
import { MetricCard } from "@/components/common/MetricCard";
import { AnalysisWorkspace } from "@/components/layout/AnalysisWorkspace";
import { AnalysisNotCompleteState } from "@/components/common/AnalysisNotCompleteState";
import { Button } from "@/components/ui/button";
import {
  TimelineLegend,
  TimelineTrack,
  TimelineNodeDetail,
  TimelineControls,
} from "@/components/timeline";
import type { EventTimelineResponse, TimelineEventNode, TimelinePhase } from "@/api/types";

const STALE_TIME = 5 * 60 * 1000;

export function buildTimelinePageUrl(
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
      const byEvent = nodes.find(
        (n) => n.root_event_id === urlEventId || n.main_chain.includes(urlEventId!) || n.tree_id === urlEventId
      );
      if (byEvent) return byEvent;
    }
    return null;
  }, [nodes, urlTreeId, urlEventId]);

  const selectionHint = useMemo(() => {
    if (!urlTreeId && !urlEventId) return null;
    if (selectedDetailNode) return null;
    if (urlTreeId) return `未定位到 tree_id=${urlTreeId} 对应的事件树。`;
    if (urlEventId) return `未定位到 event_id=${urlEventId} 对应的事件。`;
    return null;
  }, [selectedDetailNode, urlEventId, urlTreeId]);

  const selectedTrackNodeId = selectedDetailNode?.tree_id;

  const eventCount = nodes.length;
  const causalCount = causalEdges.length;
  const visibleCount = displayNodes.length;

  const handleMaxLevelChange = useCallback(
    (level: 1 | 2 | 3) => {
      if (!novelId || !taskScopeId) return;
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
    (node: TimelineEventNode) => {
      if (!novelId || !taskScopeId) return;
      const isSameNode = selectedDetailNode?.tree_id === node.tree_id;
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
      // 保留 tree 选中态，仅做章节联动（可扩展为跳转章节详情）
      navigate(`/novels/${novelId}/chapters?task_id=${taskScopeId}&chapter=${chapterId}`);
    },
    [navigate, novelId, taskScopeId]
  );

  const handleSelectTree = useCallback(
    (treeId: string) => {
      if (!novelId || !taskScopeId) return;
      // treeId 可能是 event_id，外层会按 event_id 回退查找
      const targetNode = nodes.find((n) => n.tree_id === treeId || n.root_event_id === treeId || n.main_chain.includes(treeId));
      const resolvedTreeId = targetNode?.tree_id ?? treeId;
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

  const handlePhaseClick = useCallback((phase: TimelinePhase) => {
    setActivePhase((prev) => (prev === phase.name ? undefined : phase.name));
  }, []);

  const handleRetry = useCallback(() => {
    timelineQuery.refetch();
  }, [timelineQuery]);

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
      <AnalysisWorkspace.Tabs defaultValue="timeline">
        <AnalysisWorkspace.Tab value="timeline" label="时间轴">
          <div className="flex h-full min-h-0 flex-col">
            {selectionHint ? (
              <div className="mb-3 flex items-start gap-3 rounded-2xl border border-chart-negative/20 bg-chart-negative/5 p-4">
                <AlertTriangle className="mt-0.5 h-4 w-4 text-chart-negative" />
                <p className="text-sm text-text-muted">{selectionHint}</p>
              </div>
            ) : null}

            <div className="grid gap-3 md:grid-cols-3">
              <MetricCard
                label="Events"
                value={eventCount}
                format="raw"
                accent="primary"
                icon={<Sparkles className="h-4 w-4" />}
                description="事件森林中树的数量（一树一节点）。"
                className="!p-4"
                showOrb
              />
              <MetricCard
                label="Visible"
                value={visibleCount}
                format="raw"
                accent="chart-2"
                icon={<GitBranch className="h-4 w-4" />}
                description="当前 level 筛选下可见的事件节点数量。"
                className="!p-4"
                showOrb
              />
              <MetricCard
                label="Causal"
                value={causalCount}
                format="raw"
                accent="primary"
                icon={<GitBranch className="h-4 w-4" />}
                description="全量因果边数量（含 inactive），实线活跃虚线失效。"
                className="!p-4"
                showOrb
              />
            </div>

            {!isLoading && !isError && phases.length === 0 ? (
              <div className="mt-3 rounded-2xl border border-dashed border-border/60 bg-surface/50 px-4 py-3 text-sm text-text-muted">
                暂无阶段数据
              </div>
            ) : null}

            <div className="mt-2 flex-1 min-h-0">
              {isLoading ? (
                <div className="h-[360px] w-full animate-pulse rounded-[28px] border border-border/60 bg-surface-hover" />
              ) : isAnalysisNotComplete ? (
                <div className="h-[360px] rounded-[28px] border border-border/60 bg-surface/70">
                  <AnalysisNotCompleteState
                    title={analysisFailed ? "时间轴分析任务已失败" : "时间轴结果尚未完成"}
                    description={
                      analysisFailed
                        ? "该分析任务已失败，时间轴数据无法读取，请重新发起分析后再查看。"
                        : "当前任务仍在分析中，时间轴数据暂时不可读，请等待任务进入完成态后再查看。"
                    }
                    failed={analysisFailed}
                  />
                </div>
              ) : isError ? (
                <div className="flex h-[360px] flex-col items-center justify-center gap-3 rounded-[28px] border border-border/60 bg-surface/70 text-sm text-text-muted">
                  <span>加载失败</span>
                  <Button variant="outline" size="sm" onClick={handleRetry} className="gap-2">
                    <RefreshCw className="h-4 w-4" />
                    重试
                  </Button>
                </div>
              ) : nodes.length === 0 && totalChapters === 0 ? (
                <div className="flex h-[360px] flex-col items-center justify-center gap-3 rounded-[28px] border border-border/60 bg-surface/70 text-sm text-text-muted">
                  <span>该任务为历史版本，无事件森林数据，请重新分析</span>
                  <Button variant="outline" size="sm" onClick={() => novelId && navigate(`/novels/${novelId}`)} className="gap-2">
                    <RefreshCw className="h-4 w-4" />
                    重新分析
                  </Button>
                </div>
              ) : nodes.length === 0 ? (
                <div className="flex h-[360px] items-center justify-center rounded-[28px] border border-border/60 bg-surface/70 text-sm text-text-muted">
                  暂无时间轴节点
                </div>
              ) : displayNodes.length === 0 ? (
                <div className="flex h-[360px] items-center justify-center rounded-[28px] border border-border/60 bg-surface/70 text-sm text-text-muted">
                  暂无时间轴节点
                </div>
              ) : (
                <div className="flex h-full min-h-0 flex-col gap-3 pb-2">
                  <div className="rounded-[24px] border border-border/60 bg-surface/75 px-3 py-3.5">
                    <TimelineControls variant="inline" maxLevel={maxLevel} onMaxLevelChange={handleMaxLevelChange} />

                    <div className="mt-2 flex flex-col gap-3">
                      <div className="flex min-w-0 flex-1 flex-col gap-2">
                        <div className="flex flex-wrap gap-2">
                          {phases.length === 0 ? (
                            <p className="text-sm text-text-muted">暂无阶段数据</p>
                          ) : (
                            phases.map((phase) => {
                              const isActive = activePhase === phase.name;
                              return (
                                <button
                                  key={phase.name}
                                  type="button"
                                  onClick={() => handlePhaseClick(phase)}
                                  className={[
                                    "rounded-full border px-3 py-2 text-left transition-all",
                                    isActive
                                      ? "border-primary/35 bg-primary/10 text-text shadow-sm"
                                      : "border-border/60 bg-background/70 text-text-muted hover:border-border hover:text-text",
                                  ].join(" ")}
                                >
                                  <span className="text-sm font-medium">{phase.name}</span>
                                  <span className="ml-2 text-xs">
                                    {phase.start}-{phase.end}
                                  </span>
                                </button>
                              );
                            })
                          )}
                        </div>
                      </div>

                      <TimelineLegend className="justify-start" />
                    </div>
                  </div>

                  <TimelineTrack
                    nodes={displayNodes}
                    derivedOrder={timelineData?.derived_event_order ?? []}
                    phases={phases}
                    activePhase={activePhase}
                    selectedNodeId={selectedTrackNodeId}
                    onNodeClick={handleNodeClick}
                    tensionCurve={tensionCurve ?? null}
                    totalChapters={totalChapters}
                    className="flex-1 min-h-0"
                  />
                </div>
              )}
            </div>
          </div>
        </AnalysisWorkspace.Tab>
        <AnalysisWorkspace.Tab value="detail" label="节点详情">
          <div className="h-full overflow-hidden">
            {selectedDetailNode ? (
              <TimelineNodeDetail
                node={selectedDetailNode}
                nodes={nodes}
                novelId={novelId}
                taskId={taskScopeId}
                causalEdges={causalEdges}
                foreshadowingEdges={foreshadowingEdges}
                derivedOrder={derivedOrder}
                onClose={() => {
                  navigate(
                    buildTimelinePageUrl(novelId, taskScopeId, {
                      maxLevel,
                      treeId: null,
                      eventId: null,
                    }),
                    { replace: true }
                  );
                }}
                onSelectChapter={handleSelectChapter}
                onSelectTree={handleSelectTree}
              />
            ) : (
              <div className="flex h-full min-h-[240px] items-center justify-center rounded-2xl border border-dashed border-border/60 bg-surface/50 text-sm text-text-muted">
                在时间轴中选择一个节点后查看详情。
              </div>
            )}
          </div>
        </AnalysisWorkspace.Tab>
      </AnalysisWorkspace.Tabs>
    </AnalysisWorkspace>
  );
}
