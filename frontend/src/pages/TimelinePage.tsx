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
 */

import { useEffect, useState, useCallback, useMemo, useRef } from "react";
import { useParams, useSearchParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { AlertTriangle, RefreshCw } from "lucide-react";
import { getTimeline } from "@/api/results";
import { getNovel } from "@/api/novels";
import { useNovelStore } from "@/store/novelStore";
import { PageContainer } from "@/components/layout/PageContainer";
import { NovelHeader } from "@/components/common/NovelHeader";
import { DashboardCardShell } from "@/components/common/DashboardCardShell";
import { Button } from "@/components/ui/button";
import {
  PhaseBar,
  TimelineLegend,
  TimelineTrack,
  TensionOverlay,
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
    showTension: boolean;
    selectedChunk?: number | null;
    relationEventId?: number | null;
  }
): string {
  const params = new URLSearchParams({
    task_id: taskId,
    max_level: String(options.maxLevel),
    show_tension: String(options.showTension),
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
  const urlShowTension = searchParams.get("show_tension");
  const urlSelectedChunk = searchParams.get("selected_chunk");
  const urlRelationEventId = searchParams.get("relation_event_id");
  const urlTaskSyncRef = useRef<string | null>(urlTaskId && currentTaskId !== urlTaskId ? urlTaskId : null);

  const maxLevel = useMemo<1 | 2 | 3>(() => {
    const level = urlMaxLevel ? parseInt(urlMaxLevel, 10) : 3;
    return [1, 2, 3].includes(level) ? (level as 1 | 2 | 3) : 3;
  }, [urlMaxLevel]);
  const showTension = useMemo(() => urlShowTension !== "false", [urlShowTension]);
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
        showTension,
        // 中文注释：时间轴 deep-link 选择态是 task-scoped，切任务时必须清空，
        // 否则旧任务的 relation_event_id / chunk 会污染新任务高亮。
        selectedChunk: null,
        relationEventId: null,
      }), { replace: true });
  }, [maxLevel, navigate, novelId, showTension, storeTaskId, urlTaskId]);

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

  const novelTitle = novelQuery.data?.title ?? "小说详情";

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
        showTension,
        selectedChunk: selectedNode?.chunk_id ?? selectedChunkFromUrl,
        // 中文注释：控制项变更属于“延续当前有效选择”，而不是回写失效 deep-link。
        // 一旦 relation_event_id 已无法命中当前时间轴节点，就只保留已回退成功的 chunk 选择。
        relationEventId: resolvedRelationEventId,
      }), { replace: true });
    },
    [novelId, taskScopeId, showTension, navigate, resolvedRelationEventId, selectedNode, selectedChunkFromUrl]
  );

  const handleShowTensionChange = useCallback(
    (show: boolean) => {
      if (!novelId || !taskScopeId) return;
      navigate(buildTimelinePageUrl(novelId, taskScopeId, {
        maxLevel,
        showTension: show,
        selectedChunk: selectedNode?.chunk_id ?? selectedChunkFromUrl,
        relationEventId: resolvedRelationEventId,
      }), { replace: true });
    },
    [novelId, taskScopeId, maxLevel, navigate, resolvedRelationEventId, selectedNode, selectedChunkFromUrl]
  );

  const handleNodeClick = useCallback((node: TimelineNode) => {
    if (!novelId || !taskScopeId) return;
    const nextSelectedChunk = selectedNode?.chunk_id === node.chunk_id ? null : node.chunk_id;
    navigate(
      buildTimelinePageUrl(novelId, taskScopeId, {
        maxLevel,
        showTension,
        selectedChunk: nextSelectedChunk,
        relationEventId: null,
      }),
      { replace: true }
    );
  }, [taskScopeId, maxLevel, navigate, novelId, selectedNode, showTension]);

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
        <NovelHeader title={novelTitle} />
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
      <NovelHeader title={novelTitle} />

      <div className="space-y-6">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3 }}
        >
          <TimelineControls
            maxLevel={maxLevel}
            showTension={showTension}
            onMaxLevelChange={handleMaxLevelChange}
            onShowTensionChange={handleShowTensionChange}
          />
        </motion.div>

        {selectionHint && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3, delay: 0.05 }}
          >
            <DashboardCardShell
              title="定位提示"
              icon={<AlertTriangle className="h-4 w-4" />}
              accent="chart-5"
              bodyClassName="gap-3"
            >
              <div className="flex items-start gap-3 rounded-2xl border border-chart-negative/20 bg-chart-negative/5 p-4">
                <AlertTriangle className="mt-0.5 h-4 w-4 text-chart-negative" />
                <p className="text-sm text-text-muted">{selectionHint}</p>
              </div>
            </DashboardCardShell>
          </motion.div>
        )}

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, delay: 0.1 }}
        >
          <DashboardCardShell title="叙事结构 · 四阶段" accent="chart-1" bodyClassName="gap-3">
            <div className="rounded-2xl border border-border/60 bg-surface/70 p-4">
              {isLoading ? (
                <div className="h-16 w-full animate-pulse rounded bg-surface-hover" />
              ) : isError ? (
                <div className="flex h-16 flex-col items-center justify-center gap-3 text-sm text-text-muted">
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
              ) : phases.length === 0 ? (
                <div className="flex h-16 items-center justify-center text-sm text-text-muted">
                  暂无阶段数据
                </div>
              ) : (
                <PhaseBar
                  phases={phases}
                  activePhase={activePhase}
                  onPhaseClick={handlePhaseClick}
                />
              )}
            </div>
          </DashboardCardShell>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, delay: 0.2 }}
        >
          <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_24rem]">
            <DashboardCardShell title="叙事时间轴" accent="primary" showOrb bodyClassName="gap-4">
              <div className="rounded-2xl border border-border/60 bg-surface/70 p-4">
                <p className="text-sm text-text-muted">
                  先看图例，再顺着时间轴阅读节点，点击任一节点即可在右侧查看完整事件细节。
                </p>
              </div>

              <TimelineLegend />

              <div className="rounded-2xl border border-border/60 bg-surface/70 p-4">
                {isLoading ? (
                  <div className="h-40 w-full animate-pulse rounded bg-surface-hover" />
                ) : isError ? (
                  <div className="flex h-40 flex-col items-center justify-center gap-3 text-sm text-text-muted">
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
                  <div className="flex h-40 items-center justify-center text-sm text-text-muted">
                    暂无时间轴节点
                  </div>
                ) : (
                  <TimelineTrack
                    nodes={nodes}
                    phases={phases}
                    activePhase={activePhase}
                    selectedNodeId={selectedNode?.chunk_id}
                    onNodeClick={handleNodeClick}
                  />
                )}
              </div>

              {showTension && tensionCurve && tensionCurve.length > 0 ? (
                <div className="rounded-2xl border border-border/60 bg-surface/70 p-4">
                  <div className="mb-3 flex items-center justify-between gap-3">
                    <div>
                      <p className="text-sm font-medium text-text">张力走势</p>
                      <p className="text-xs text-text-muted">
                        下方曲线帮助判断节点为何会在轨道上方或下方起伏。
                      </p>
                    </div>
                  </div>
                  <TensionOverlay
                    tensionCurve={tensionCurve}
                    totalChunks={totalChunks}
                    height={160}
                  />
                </div>
              ) : (
                <div className="rounded-2xl border border-dashed border-border/60 bg-surface/40 p-4 text-sm text-text-muted">
                  当前已隐藏张力曲线。若需要把节点高低与节奏走势一起看，可以在上方控制区重新开启。
                </div>
              )}
            </DashboardCardShell>

            {novelId && (
              selectedNode ? (
                <TimelineNodeDetail
                  className="xl:sticky xl:top-6"
                  node={selectedNode}
                  novelId={novelId}
                  taskId={taskScopeId}
                  selectedRelationEventId={resolvedRelationEventId}
                  onClose={() => {
                    navigate(
                      buildTimelinePageUrl(novelId, taskScopeId, {
                        maxLevel,
                        showTension,
                        selectedChunk: null,
                        relationEventId: null,
                      }),
                      { replace: true }
                    );
                  }}
                />
              ) : (
                <DashboardCardShell
                  title="节点详情"
                  accent="chart-2"
                  className="xl:sticky xl:top-6"
                  bodyClassName="gap-4"
                >
                  <div className="rounded-2xl border border-dashed border-border/60 bg-surface/50 p-5">
                    <p className="text-sm font-medium text-text">点击任意节点查看详情</p>
                    <p className="mt-2 text-sm leading-6 text-text-muted">
                      右侧会展示事件描述、涉及角色、关系变化以及回跳到图谱的入口。
                      如果你正在排查某个关系事件，优先点亮蓝色“关系变化”节点会更直接。
                    </p>
                  </div>
                  <div className="rounded-2xl border border-border/60 bg-surface/60 p-4 text-sm text-text-muted">
                    当前没有选中节点，因此这里只显示阅读提示，不再把详情卡片挤到张力曲线下方。
                  </div>
                </DashboardCardShell>
              )
            )}
          </div>
        </motion.div>
      </div>
    </PageContainer>
  );
}
