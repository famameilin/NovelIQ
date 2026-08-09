/** 展示叙事时间轴、节点详情和双层节点视图切换 */

import { useEffect, useState, useCallback, useMemo, useRef } from "react";
import { useParams, useSearchParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, GitBranch, RefreshCw, Sparkles, TrendingUp } from "lucide-react";
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
import type { TimelineCompositeNode, TimelineNode, TimelinePhase } from "@/api/types";

const STALE_TIME = 5 * 60 * 1000;

type TimelineViewMode = "composite" | "atomic";
type TimelineDisplayNode = TimelineNode | TimelineCompositeNode;

function buildTimelinePageUrl(
  novelId: string,
  taskId: string,
  options: {
    maxLevel: 1 | 2 | 3;
    viewMode: TimelineViewMode;
    selectedNodeId?: string | null;
    selectedChunk?: number | null;
    changeId?: string | null;
  }
): string {
  const params = new URLSearchParams({
    task_id: taskId,
    max_level: String(options.maxLevel),
    view: options.viewMode,
  });
  if (options.selectedNodeId) {
    params.set("selected_node_id", options.selectedNodeId);
  }
  if (options.selectedChunk != null) {
    params.set("selected_chunk", String(options.selectedChunk));
  }
  if (options.changeId) {
    params.set("change_id", options.changeId);
  }
  return `/novels/${novelId}/timeline?${params.toString()}`;
}

function isAtomicTimelineNode(node: TimelineDisplayNode | null): node is TimelineNode {
  return node != null && "node_subtype" in node;
}

function isCompositeTimelineNode(node: TimelineDisplayNode | null): node is TimelineCompositeNode {
  return node != null && "child_node_ids" in node;
}

/** 只有当 change_id 真正属于当前节点时，才继续保留它 */
function getSelectedNodeGraphChangeId(node: TimelineDisplayNode | null, changeId: string | null): string | null {
  if (!isAtomicTimelineNode(node) || changeId == null) {
    return null;
  }
  const belongsToSelectedNode =
    node.graph_changes?.some((change) => change.change_id === changeId) ?? false;
  return belongsToSelectedNode ? changeId : null;
}

/**
 * 2026-04-28，任务：分析详情页单屏 Tabs 改造
 * 修改原因：时间轴轨道与节点详情拆成 tab，保证轨道首屏优先且详情不再撑高页面
 */
export function TimelinePage() {
  const { novelId } = useParams<{ novelId: string }>();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { currentNovelId, currentTaskId, setNovel, setTask } = useNovelStore();

  const urlTaskId = searchParams.get("task_id");
  const urlMaxLevel = searchParams.get("max_level");
  const urlView = searchParams.get("view");
  const urlSelectedNodeId = searchParams.get("selected_node_id");
  const urlSelectedChunk = searchParams.get("selected_chunk");
  const urlChangeId = searchParams.get("change_id");
  const urlTaskSyncRef = useRef<string | null>(urlTaskId && currentTaskId !== urlTaskId ? urlTaskId : null);

  const maxLevel = useMemo<1 | 2 | 3>(() => {
    const level = urlMaxLevel ? parseInt(urlMaxLevel, 10) : 3;
    return [1, 2, 3].includes(level) ? (level as 1 | 2 | 3) : 3;
  }, [urlMaxLevel]);
  const viewMode = useMemo<TimelineViewMode>(() => {
    return urlView === "atomic" ? "atomic" : "composite";
  }, [urlView]);
  const showTension = true;
  const [activePhase, setActivePhase] = useState<string | undefined>();
  const storeTaskId = currentNovelId === novelId ? currentTaskId : null;
  const taskScopeId = urlTaskId ?? storeTaskId;

  const selectedChunkFromUrl = useMemo(() => {
    if (!urlSelectedChunk) return null;
    const parsed = Number(urlSelectedChunk);
    return Number.isFinite(parsed) ? parsed : null;
  }, [urlSelectedChunk]);

  const changeIdFromUrl = useMemo(() => urlChangeId?.trim() || null, [urlChangeId]);

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
    if (!novelId || !storeTaskId) {
      return;
    }
    if (urlTaskId === storeTaskId) {
      if (urlTaskSyncRef.current === storeTaskId) {
        urlTaskSyncRef.current = null;
      }
      return;
    }
    if (urlTaskId && urlTaskSyncRef.current === urlTaskId) {
      return;
    }

    navigate(buildTimelinePageUrl(novelId, storeTaskId, {
        maxLevel,
        viewMode,
        // 时间轴 deep-link 选择态是 task-scoped，切任务时必须清空，
        // 否则旧任务的 change_id / chunk 会污染新任务高亮
        selectedNodeId: null,
        selectedChunk: null,
        changeId: null,
      }), { replace: true });
  }, [maxLevel, navigate, novelId, storeTaskId, urlTaskId, viewMode]);

  const enabled = !!novelId && !!taskScopeId;

  const timelineQuery = useQuery({
    queryKey: ["timeline", novelId, taskScopeId],
    queryFn: () =>
      getTimeline(novelId!, taskScopeId!, {
        includeCurve: true,
      }),
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
  const atomicNodes = useMemo(() => timelineData?.atomic_nodes ?? [], [timelineData?.atomic_nodes]);
  const compositeNodes = useMemo(() => timelineData?.composite_nodes ?? [], [timelineData?.composite_nodes]);
  const tensionCurve = timelineData?.tension_curve;
  const totalChunks = timelineData?.meta?.total_chunks ?? 0;
  const visibleAtomicNodes = useMemo(
    () => atomicNodes.filter((node) => node.level <= maxLevel),
    [atomicNodes, maxLevel],
  );
  const visibleCompositeNodes = useMemo(
    () => compositeNodes.filter((node) => node.level <= maxLevel),
    [compositeNodes, maxLevel],
  );
  const displayNodes = useMemo<TimelineDisplayNode[]>(
    () => (viewMode === "atomic" ? visibleAtomicNodes : visibleCompositeNodes),
    [viewMode, visibleAtomicNodes, visibleCompositeNodes],
  );
  const atomicNodeById = useMemo(
    () => new Map(atomicNodes.map((node) => [node.node_id, node])),
    [atomicNodes],
  );
  const compositeNodeById = useMemo(
    () => new Map(compositeNodes.map((node) => [node.node_id, node])),
    [compositeNodes],
  );
  const parentCompositeByChildId = useMemo(() => {
    const parentMap = new Map<string, TimelineCompositeNode>();
    compositeNodes.forEach((compositeNode) => {
      compositeNode.child_node_ids.forEach((childNodeId) => {
        if (!parentMap.has(childNodeId)) {
          parentMap.set(childNodeId, compositeNode);
        }
      });
    });
    return parentMap;
  }, [compositeNodes]);
  const matchedGraphChangeNode = useMemo(() => {
    if (changeIdFromUrl == null) return null;
    return (
      atomicNodes.find((node) =>
        node.graph_changes?.some((change) => change.change_id === changeIdFromUrl)
      ) ?? null
    );
  }, [atomicNodes, changeIdFromUrl]);
  const selectedNodeById = useMemo<TimelineDisplayNode | null>(() => {
    if (!urlSelectedNodeId) return null;
    return compositeNodeById.get(urlSelectedNodeId) ?? atomicNodeById.get(urlSelectedNodeId) ?? null;
  }, [atomicNodeById, compositeNodeById, urlSelectedNodeId]);
  const selectedChunkCandidates = useMemo(() => {
    if (selectedChunkFromUrl == null) return [];
    return displayNodes.filter((node) => node.anchor_chunk_id === selectedChunkFromUrl);
  }, [displayNodes, selectedChunkFromUrl]);
  const selectedDetailNode = useMemo<TimelineDisplayNode | null>(() => {
    if (atomicNodes.length === 0 && compositeNodes.length === 0) return null;
    if (selectedNodeById) {
      return selectedNodeById;
    }
    if (matchedGraphChangeNode) {
      return matchedGraphChangeNode;
    }
    if (selectedChunkFromUrl != null) {
      return selectedChunkCandidates.length === 1 ? selectedChunkCandidates[0] ?? null : null;
    }
    return null;
  }, [atomicNodes.length, compositeNodes.length, matchedGraphChangeNode, selectedChunkCandidates, selectedChunkFromUrl, selectedNodeById]);
  const resolvedGraphChangeId = useMemo(
    () => getSelectedNodeGraphChangeId(selectedDetailNode, changeIdFromUrl),
    [changeIdFromUrl, selectedDetailNode]
  );
  const pivotCount = useMemo(
    () => visibleAtomicNodes.filter((node) => node.plot_flags?.is_pivot).length,
    [visibleAtomicNodes]
  );
  const relationChangeCount = useMemo(
    () => visibleAtomicNodes.filter((node) => node.node_type === "relation").length,
    [visibleAtomicNodes]
  );
  const selectionHint = useMemo(() => {
    if (changeIdFromUrl == null) return null;
    if (matchedGraphChangeNode) return null;
    if (selectedChunkFromUrl != null && selectedDetailNode) {
      return "未定位到指定图谱变化，已回退到对应时间节点。";
    }
    return "未定位到对应图谱变化。";
  }, [changeIdFromUrl, matchedGraphChangeNode, selectedChunkFromUrl, selectedDetailNode]);
  const chunkSelectionHint = useMemo(() => {
    if (changeIdFromUrl != null || selectedChunkFromUrl == null) {
      return null;
    }
    if (selectedDetailNode != null) {
      return null;
    }
    if (selectedChunkCandidates.length > 1) {
      return "该时间块包含多个不同类型节点，请使用稳定节点链接重新定位。";
    }
    if (selectedChunkCandidates.length === 0) {
      return "未定位到对应时间节点。";
    }
    return null;
  }, [changeIdFromUrl, selectedChunkCandidates, selectedChunkFromUrl, selectedDetailNode]);
  const selectedTrackNodeId = useMemo(() => {
    if (selectedDetailNode == null) {
      return undefined;
    }
    if (viewMode === "atomic") {
      if (isCompositeTimelineNode(selectedDetailNode)) {
        return selectedDetailNode.representative_node_id;
      }
      return selectedDetailNode.node_id;
    }
    if (isCompositeTimelineNode(selectedDetailNode)) {
      return selectedDetailNode.node_id;
    }
    return parentCompositeByChildId.get(selectedDetailNode.node_id)?.node_id;
  }, [parentCompositeByChildId, selectedDetailNode, viewMode]);

  const handleMaxLevelChange = useCallback(
    (level: 1 | 2 | 3) => {
      if (!novelId || !taskScopeId) return;
      navigate(buildTimelinePageUrl(novelId, taskScopeId, {
        maxLevel: level,
        viewMode,
        selectedNodeId: selectedDetailNode?.node_id ?? null,
        selectedChunk: selectedDetailNode?.anchor_chunk_id ?? selectedChunkFromUrl,
        // 控制项变更属于“延续当前有效选择”，而不是回写失效 deep-link
        // 一旦 change_id 已无法命中当前时间轴节点，就只保留已回退成功的 chunk 选择
        changeId: resolvedGraphChangeId,
      }), { replace: true });
    },
    [novelId, taskScopeId, navigate, resolvedGraphChangeId, selectedDetailNode, selectedChunkFromUrl, viewMode]
  );

  const handleViewModeChange = useCallback(
    (nextViewMode: TimelineViewMode) => {
      if (!novelId || !taskScopeId) return;
      navigate(
        buildTimelinePageUrl(novelId, taskScopeId, {
          maxLevel,
          viewMode: nextViewMode,
          selectedNodeId: selectedDetailNode?.node_id ?? null,
          selectedChunk: selectedDetailNode?.anchor_chunk_id ?? selectedChunkFromUrl,
          changeId: resolvedGraphChangeId,
        }),
        { replace: true }
      );
    },
    [maxLevel, navigate, novelId, resolvedGraphChangeId, selectedDetailNode, selectedChunkFromUrl, taskScopeId]
  );

  const handleNodeClick = useCallback((node: TimelineDisplayNode) => {
    if (!novelId || !taskScopeId) return;
    const isSameNode = selectedDetailNode?.node_id === node.node_id;
    navigate(
      buildTimelinePageUrl(novelId, taskScopeId, {
        maxLevel,
        viewMode,
        selectedNodeId: isSameNode ? null : node.node_id,
        selectedChunk: isSameNode ? null : node.anchor_chunk_id,
        changeId: null,
      }),
      { replace: true }
    );
  }, [taskScopeId, maxLevel, navigate, novelId, selectedDetailNode, viewMode]);

  const handleSelectAtomicNode = useCallback(
    (node: TimelineNode) => {
      if (!novelId || !taskScopeId) return;
      const changeId =
        (node.graph_changes?.length ?? 0) === 1
          ? node.graph_changes?.[0]?.change_id ?? null
          : null;
      navigate(
        buildTimelinePageUrl(novelId, taskScopeId, {
          maxLevel,
          viewMode: "atomic",
          selectedNodeId: node.node_id,
          selectedChunk: node.anchor_chunk_id,
          changeId,
        }),
        { replace: true }
      );
    },
    [maxLevel, navigate, novelId, taskScopeId]
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
            <p className="mt-1 text-sm text-text-muted">
              请从小说列表中选择一本小说
            </p>
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
            <p className="mt-1 text-sm text-text-muted">
              使用顶部任务选择器选择一个已完成的任务以查看时间轴
            </p>
          </div>
        </div>
      </AnalysisWorkspace>
    );
  }

  return (
    <AnalysisWorkspace title="叙事时间轴">
      {/*
        2026-04-28，任务：分析详情页单屏 Tabs 改造
        修改原因：时间轴页以轨道为第一工作区，节点详情拆到独立 tab，由单屏工作区统一约束边界。
      */}
      <AnalysisWorkspace.Tabs defaultValue="timeline">
        <AnalysisWorkspace.Tab value="timeline" label="时间轴">
          <div className="flex h-full min-h-0 flex-col">
            {(selectionHint || chunkSelectionHint) && (
              <div className="mb-3 flex items-start gap-3 rounded-2xl border border-chart-negative/20 bg-chart-negative/5 p-4">
                <AlertTriangle className="mt-0.5 h-4 w-4 text-chart-negative" />
                <p className="text-sm text-text-muted">{selectionHint ?? chunkSelectionHint}</p>
              </div>
            )}

            <div className="grid gap-3 md:grid-cols-3">
              <MetricCard
                label="Overview"
                value={displayNodes.length}
                format="raw"
                accent="chart-1"
                icon={<TrendingUp className="h-4 w-4" />}
                description="当前视图与筛选层级下可见的时间轴节点数量。"
                className="!p-4"
                showOrb
              />
              <MetricCard
                label="Pivot"
                value={pivotCount}
                format="raw"
                accent="chart-5"
                icon={<Sparkles className="h-4 w-4" />}
                description="被标记为转折点的节点数量，适合优先阅读。"
                className="!p-4"
                showOrb
              />
              <MetricCard
                label="Relation"
                value={relationChangeCount}
                format="raw"
                accent="chart-2"
                icon={<GitBranch className="h-4 w-4" />}
                description="关系变化节点数量，通常最适合联动图谱排查。"
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
              ) : displayNodes.length === 0 ? (
                <div className="flex h-[360px] items-center justify-center rounded-[28px] border border-border/60 bg-surface/70 text-sm text-text-muted">
                  暂无时间轴节点
                </div>
              ) : (
                <div className="flex h-full min-h-0 flex-col gap-3 pb-2">
                  <div className="rounded-[24px] border border-border/60 bg-surface/75 px-3 py-3.5">
                    <TimelineControls
                      variant="inline"
                      maxLevel={maxLevel}
                      onMaxLevelChange={handleMaxLevelChange}
                      viewMode={viewMode}
                      onViewModeChange={handleViewModeChange}
                    />

                    <div className="mt-2 flex flex-col gap-2 xl:flex-row xl:items-start xl:justify-between">
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
                                <span className="ml-2 text-xs">{phase.start}-{phase.end}</span>
                              </button>
                            );
                          })
                        )}
                      </div>

                      <TimelineLegend className="xl:justify-end" />
                    </div>
                  </div>

                  <TimelineTrack
                    nodes={displayNodes}
                    phases={phases}
                    activePhase={activePhase}
                    selectedNodeId={selectedTrackNodeId}
                    onNodeClick={handleNodeClick}
                    tensionCurve={tensionCurve}
                    totalChunks={totalChunks}
                    showTension={showTension}
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
                atomicNodes={atomicNodes}
                novelId={novelId}
                taskId={taskScopeId}
                selectedGraphChangeId={resolvedGraphChangeId}
                onSelectAtomicNode={handleSelectAtomicNode}
                onClose={() => {
                  navigate(
                    buildTimelinePageUrl(novelId, taskScopeId, {
                      maxLevel,
                      viewMode,
                      selectedNodeId: null,
                      selectedChunk: null,
                      changeId: null,
                    }),
                    { replace: true }
                  );
                }}
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
