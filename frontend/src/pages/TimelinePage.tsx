/**
 * TimelinePage - 叙事时间轴页面
 *
 * 创建时间: 2026-04-05
 * 创建者: GLM-5
 * 任务: Phase 2-B 叙事时间轴
 * 说明: 完整叙事时间轴页面，展示四阶段划分、关键事件节点、张力曲线叠加
 *
 * 修改时间: 2026-04-21
 * 任务: 修复叙事时间轴页面布局与节点语义表达
 * 修改内容:
 *   - 重组时间轴主体布局，将轨道、图例、张力区收敛到同一信息区
 *   - 将节点详情移到桌面端右侧，避免点击后还要滚到张力曲线下方阅读
 *   - 为未选中节点的状态补充明确引导，减少页面空白感
 *
 * 修改时间: 2026-04-21
 * 任务: 对齐时间轴页与主题页的头部表现
 * 修改内容:
 *   - 统一使用 NovelHeader 承担页面标题，避免重复标题层级
 *   - 移除页面内额外说明文案，使时间轴页与主题页保持一致的头部结构
 */

import { useEffect, useState, useCallback, useMemo, useRef } from "react";
import { useParams, useSearchParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { AlertTriangle, GitBranch, RefreshCw, Sparkles, TrendingUp } from "lucide-react";
import { getTimeline } from "@/api/results";
import { getNovel } from "@/api/novels";
import { useNovelStore } from "@/store/novelStore";
import { MetricCard } from "@/components/common/MetricCard";
import { PageContainer } from "@/components/layout/PageContainer";
import { NovelHeader } from "@/components/common/NovelHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  TimelineLegend,
  TimelineTrack,
  TimelineNodeDetail,
  TimelineControls,
} from "@/components/timeline";
import type { TimelineNode, TimelinePhase } from "@/api/types";

/* ------------------------------------------------------------------ */
/*  Constants                                                         */
/* ------------------------------------------------------------------ */

const STALE_TIME = 5 * 60 * 1000;

function buildTimelinePageUrl(
  novelId: string,
  taskId: string,
  options: {
    maxLevel: 1 | 2 | 3;
    selectedChunk?: number | null;
    relationEventId?: number | null;
  }
): string {
  const params = new URLSearchParams({
    task_id: taskId,
    max_level: String(options.maxLevel),
  });
  if (options.selectedChunk != null) {
    params.set("selected_chunk", String(options.selectedChunk));
  }
  if (options.relationEventId != null) {
    params.set("relation_event_id", String(options.relationEventId));
  }
  return `/novels/${novelId}/timeline?${params.toString()}`;
}

/* ------------------------------------------------------------------ */
/*  Main Component                                                    */
/* ------------------------------------------------------------------ */

export function TimelinePage() {
  const { novelId } = useParams<{ novelId: string }>();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { currentNovelId, currentTaskId, setNovel, setTask } = useNovelStore();

  const urlTaskId = searchParams.get("task_id");
  const urlMaxLevel = searchParams.get("max_level");
  const urlSelectedChunk = searchParams.get("selected_chunk");
  const urlRelationEventId = searchParams.get("relation_event_id");
  const urlTaskSyncRef = useRef<string | null>(urlTaskId && currentTaskId !== urlTaskId ? urlTaskId : null);

  const maxLevel = useMemo<1 | 2 | 3>(() => {
    const level = urlMaxLevel ? parseInt(urlMaxLevel, 10) : 3;
    return [1, 2, 3].includes(level) ? (level as 1 | 2 | 3) : 3;
  }, [urlMaxLevel]);
  const showTension = true;
  const [activePhase, setActivePhase] = useState<string | undefined>();
  const storeTaskId = currentNovelId === novelId ? currentTaskId : null;
  const taskScopeId = urlTaskId ?? storeTaskId;

  const selectedChunkFromUrl = useMemo(() => {
    if (!urlSelectedChunk) return null;
    const parsed = Number(urlSelectedChunk);
    return Number.isFinite(parsed) ? parsed : null;
  }, [urlSelectedChunk]);

  const relationEventIdFromUrl = useMemo(() => {
    if (!urlRelationEventId) return null;
    const parsed = Number(urlRelationEventId);
    return Number.isInteger(parsed) ? parsed : null;
  }, [urlRelationEventId]);

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
        // 中文注释：时间轴 deep-link 选择态是 task-scoped，切任务时必须清空，
        // 否则旧任务的 relation_event_id / chunk 会污染新任务高亮。
        selectedChunk: null,
        relationEventId: null,
      }), { replace: true });
  }, [maxLevel, navigate, novelId, storeTaskId, urlTaskId]);

  const enabled = !!novelId && !!taskScopeId;

  const timelineQuery = useQuery({
    queryKey: ["timeline", novelId, taskScopeId, maxLevel],
    queryFn: () =>
      getTimeline(novelId!, taskScopeId!, {
        includeCurve: true,
        maxLevel: maxLevel,
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
  const nodes = useMemo(() => timelineData?.nodes ?? [], [timelineData?.nodes]);
  const tensionCurve = timelineData?.tension_curve;
  const totalChunks = timelineData?.meta?.total_chunks ?? 0;
  const matchedRelationEventNode = useMemo(() => {
    if (relationEventIdFromUrl == null) return null;
    return (
      nodes.find((node) =>
        node.relation_changes?.some((relationChange) => relationChange.relation_event_id === relationEventIdFromUrl)
      ) ?? null
    );
  }, [nodes, relationEventIdFromUrl]);
  const selectedNode = useMemo(() => {
    if (nodes.length === 0) return null;
    if (matchedRelationEventNode) {
      return matchedRelationEventNode;
    }
    if (selectedChunkFromUrl != null) {
      return nodes.find((node) => node.chunk_id === selectedChunkFromUrl) ?? null;
    }
    return null;
  }, [matchedRelationEventNode, nodes, selectedChunkFromUrl]);
  const resolvedRelationEventId = matchedRelationEventNode ? relationEventIdFromUrl : null;
  const pivotCount = useMemo(() => nodes.filter((node) => node.is_pivot).length, [nodes]);
  const relationChangeCount = useMemo(
    () => nodes.filter((node) => node.node_type === "relation_change").length,
    [nodes]
  );
  const selectionHint = useMemo(() => {
    if (relationEventIdFromUrl == null) return null;
    if (matchedRelationEventNode) return null;
    if (selectedChunkFromUrl != null && selectedNode) {
      return "未定位到指定关系事件，已回退到对应时间节点。";
    }
    return "未定位到对应事件。";
  }, [matchedRelationEventNode, relationEventIdFromUrl, selectedChunkFromUrl, selectedNode]);

  const handleMaxLevelChange = useCallback(
    (level: 1 | 2 | 3) => {
      if (!novelId || !taskScopeId) return;
      navigate(buildTimelinePageUrl(novelId, taskScopeId, {
        maxLevel: level,
        selectedChunk: selectedNode?.chunk_id ?? selectedChunkFromUrl,
        // 中文注释：控制项变更属于“延续当前有效选择”，而不是回写失效 deep-link。
        // 一旦 relation_event_id 已无法命中当前时间轴节点，就只保留已回退成功的 chunk 选择。
        relationEventId: resolvedRelationEventId,
      }), { replace: true });
    },
    [novelId, taskScopeId, navigate, resolvedRelationEventId, selectedNode, selectedChunkFromUrl]
  );

  const handleNodeClick = useCallback((node: TimelineNode) => {
    if (!novelId || !taskScopeId) return;
    const nextSelectedChunk = selectedNode?.chunk_id === node.chunk_id ? null : node.chunk_id;
    navigate(
      buildTimelinePageUrl(novelId, taskScopeId, {
        maxLevel,
        selectedChunk: nextSelectedChunk,
        relationEventId: null,
      }),
      { replace: true }
    );
  }, [taskScopeId, maxLevel, navigate, novelId, selectedNode]);

  const handlePhaseClick = useCallback((phase: TimelinePhase) => {
    setActivePhase((prev) => (prev === phase.name ? undefined : phase.name));
  }, []);

  const handleRetry = useCallback(() => {
    timelineQuery.refetch();
  }, [timelineQuery]);

  const isLoading = timelineQuery.isLoading || novelQuery.isLoading;
  const isError = timelineQuery.isError || novelQuery.isError;

  if (!novelId) {
    return (
      <PageContainer>
        <div className="flex h-96 flex-col items-center justify-center gap-4">
          <div className="text-center">
            <h3 className="text-lg font-semibold text-text">小说不存在</h3>
            <p className="mt-1 text-sm text-text-muted">
              请从小说列表中选择一本小说
            </p>
          </div>
        </div>
      </PageContainer>
    );
  }

  if (!taskScopeId) {
    return (
      <PageContainer>
        <NovelHeader title="叙事时间轴" />
        <div className="flex h-96 flex-col items-center justify-center gap-4">
          <div className="text-center">
            <h3 className="text-lg font-semibold text-text">请先选择分析任务</h3>
            <p className="mt-1 text-sm text-text-muted">
              使用顶部任务选择器选择一个已完成的任务以查看时间轴
            </p>
          </div>
        </div>
      </PageContainer>
    );
  }

  return (
    <PageContainer>
      <NovelHeader title="叙事时间轴" />

      <div className="mt-4 space-y-6">
        {selectionHint && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3, delay: 0.05 }}
          >
            <div className="flex items-start gap-3 rounded-2xl border border-chart-negative/20 bg-chart-negative/5 p-4">
              <AlertTriangle className="mt-0.5 h-4 w-4 text-chart-negative" />
              <p className="text-sm text-text-muted">{selectionHint}</p>
            </div>
          </motion.div>
        )}

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, delay: 0.1 }}
        >
          <div className="space-y-4">
              <div className="grid gap-3 md:grid-cols-3">
                <MetricCard
                  label="Overview"
                  value={nodes.length}
                  format="raw"
                  accent="chart-1"
                  icon={<TrendingUp className="h-5 w-5" />}
                  description="当前筛选层级下保留下来的关键叙事节点数量。"
                  footer={<p className="mt-3 text-sm text-text-muted">当前筛选下的关键叙事节点</p>}
                  showOrb
                />
                <MetricCard
                  label="Pivot"
                  value={pivotCount}
                  format="raw"
                  accent="chart-5"
                  icon={<Sparkles className="h-5 w-5" />}
                  description="被标记为转折点的节点数量，适合优先阅读。"
                  footer={<p className="mt-3 text-sm text-text-muted">转折点，适合优先阅读</p>}
                  showOrb
                />
                <MetricCard
                  label="Relation"
                  value={relationChangeCount}
                  format="raw"
                  accent="chart-2"
                  icon={<GitBranch className="h-5 w-5" />}
                  description="关系变化节点数量，通常最适合联动图谱排查。"
                  footer={<p className="mt-3 text-sm text-text-muted">关系变化节点，最适合联动图谱排查</p>}
                  showOrb
                />
              </div>

              {!isLoading && !isError && phases.length === 0 ? (
                <div className="rounded-2xl border border-dashed border-border/60 bg-surface/50 px-4 py-3 text-sm text-text-muted">
                  暂无阶段数据
                </div>
              ) : null}

              {isLoading ? (
                <div className="h-[360px] w-full animate-pulse rounded-[28px] border border-border/60 bg-surface-hover" />
              ) : isError ? (
                <div className="flex h-[360px] flex-col items-center justify-center gap-3 rounded-[28px] border border-border/60 bg-surface/70 text-sm text-text-muted">
                  <span>加载失败</span>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={handleRetry}
                    className="gap-2"
                  >
                    <RefreshCw className="h-4 w-4" />
                    重试
                  </Button>
                </div>
              ) : nodes.length === 0 ? (
                <div className="flex h-[360px] items-center justify-center rounded-[28px] border border-border/60 bg-surface/70 text-sm text-text-muted">
                  暂无时间轴节点
                </div>
              ) : (
                <div className="space-y-4 pb-4">
                  <div className="rounded-[28px] border border-border/60 bg-surface/75 p-4">
                    <TimelineControls
                      variant="inline"
                      maxLevel={maxLevel}
                      onMaxLevelChange={handleMaxLevelChange}
                    />

                    <div className="mt-4 flex flex-wrap gap-2">
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

                    <TimelineLegend className="mt-4" />
                  </div>

                  <TimelineTrack
                    nodes={nodes}
                    phases={phases}
                    activePhase={activePhase}
                    selectedNodeId={selectedNode?.chunk_id}
                    onNodeClick={handleNodeClick}
                    tensionCurve={tensionCurve}
                    totalChunks={totalChunks}
                    showTension={showTension}
                  />

                  {selectedNode ? (
                    <TimelineNodeDetail
                      node={selectedNode}
                      novelId={novelId}
                      taskId={taskScopeId}
                      selectedRelationEventId={resolvedRelationEventId}
                      onClose={() => {
                        navigate(
                          buildTimelinePageUrl(novelId, taskScopeId, {
                            maxLevel,
                            selectedChunk: null,
                            relationEventId: null,
                          }),
                          { replace: true }
                        );
                      }}
                    />
                  ) : null}
                </div>
              )}
          </div>
        </motion.div>
      </div>
    </PageContainer>
  );
}
