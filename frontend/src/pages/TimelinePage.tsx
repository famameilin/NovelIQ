/**
 * TimelinePage - 叙事时间轴页面
 *
 * 创建时间: 2026-04-05
 * 创建者: GLM-5
 * 任务: Phase 2-B 叙事时间轴
 * 说明: 完整叙事时间轴页面，展示四阶段划分、关键事件节点、张力曲线叠加
 */

import { useEffect, useState, useCallback, useMemo } from "react";
import { useParams, useSearchParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { AlertTriangle, RefreshCw } from "lucide-react";
import { getTimeline } from "@/api/results";
import { getNovel } from "@/api/novels";
import { useNovelStore } from "@/store/novelStore";
import { PageContainer } from "@/components/layout/PageContainer";
import { NovelHeader } from "@/components/common/NovelHeader";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  PhaseBar,
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
  const { currentTaskId, setNovel, setTask } = useNovelStore();

  const urlTaskId = searchParams.get("task_id");
  const urlMaxLevel = searchParams.get("max_level");
  const urlShowTension = searchParams.get("show_tension");
  const urlSelectedChunk = searchParams.get("selected_chunk");
  const urlRelationEventId = searchParams.get("relation_event_id");

  const [maxLevel, setMaxLevel] = useState<1 | 2 | 3>(() => {
    const level = urlMaxLevel ? parseInt(urlMaxLevel, 10) : 3;
    return [1, 2, 3].includes(level) ? (level as 1 | 2 | 3) : 3;
  });
  const [showTension, setShowTension] = useState(urlShowTension !== "false");
  const [activePhase, setActivePhase] = useState<string | undefined>();

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
        setTask(urlTaskId);
      }
    }
  }, [novelId, urlTaskId, setNovel, setTask]);

  useEffect(() => {
    if (currentTaskId && novelId && urlTaskId !== currentTaskId) {
      navigate(buildTimelinePageUrl(novelId, currentTaskId, {
        maxLevel,
        showTension,
        // 中文注释：时间轴 deep-link 选择态是 task-scoped，切任务时必须清空，
        // 否则旧任务的 relation_event_id / chunk 会污染新任务高亮。
        selectedChunk: null,
        relationEventId: null,
      }), { replace: true });
    }
  }, [currentTaskId, novelId, navigate, urlTaskId, maxLevel, showTension, selectedChunkFromUrl, relationEventIdFromUrl]);

  const enabled = !!novelId && !!currentTaskId;

  const timelineQuery = useQuery({
    queryKey: ["timeline", novelId, currentTaskId, maxLevel],
    queryFn: () =>
      getTimeline(novelId!, currentTaskId!, {
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
  const selectedNode = useMemo(() => {
    if (nodes.length === 0) return null;
    if (relationEventIdFromUrl != null) {
      const matchedRelationNode =
        nodes.find((node) =>
          node.relation_changes?.some((relationChange) => relationChange.relation_event_id === relationEventIdFromUrl)
        ) ?? null;
      if (matchedRelationNode) {
        return matchedRelationNode;
      }
    }
    if (selectedChunkFromUrl != null) {
      return nodes.find((node) => node.chunk_id === selectedChunkFromUrl) ?? null;
    }
    return null;
  }, [nodes, relationEventIdFromUrl, selectedChunkFromUrl]);
  const selectionHint = useMemo(() => {
    if (relationEventIdFromUrl == null) return null;
    const matchedRelationNode = nodes.find((node) =>
      node.relation_changes?.some((relationChange) => relationChange.relation_event_id === relationEventIdFromUrl)
    );
    if (matchedRelationNode) return null;
    if (selectedChunkFromUrl != null && selectedNode) {
      return "未定位到指定关系事件，已回退到对应时间节点。";
    }
    return "未定位到对应事件。";
  }, [nodes, relationEventIdFromUrl, selectedChunkFromUrl, selectedNode]);

  const handleMaxLevelChange = useCallback(
    (level: 1 | 2 | 3) => {
      setMaxLevel(level);
      if (!novelId || !currentTaskId) return;
      navigate(buildTimelinePageUrl(novelId, currentTaskId, {
        maxLevel: level,
        showTension,
        selectedChunk: selectedNode?.chunk_id ?? selectedChunkFromUrl,
        relationEventId: relationEventIdFromUrl,
      }), { replace: true });
    },
    [novelId, currentTaskId, showTension, navigate, selectedNode, selectedChunkFromUrl, relationEventIdFromUrl]
  );

  const handleShowTensionChange = useCallback(
    (show: boolean) => {
      setShowTension(show);
      if (!novelId || !currentTaskId) return;
      navigate(buildTimelinePageUrl(novelId, currentTaskId, {
        maxLevel,
        showTension: show,
        selectedChunk: selectedNode?.chunk_id ?? selectedChunkFromUrl,
        relationEventId: relationEventIdFromUrl,
      }), { replace: true });
    },
    [novelId, currentTaskId, maxLevel, navigate, selectedNode, selectedChunkFromUrl, relationEventIdFromUrl]
  );

  const handleNodeClick = useCallback((node: TimelineNode) => {
    if (!novelId || !currentTaskId) return;
    const nextSelectedChunk = selectedNode?.chunk_id === node.chunk_id ? null : node.chunk_id;
    navigate(
      buildTimelinePageUrl(novelId, currentTaskId, {
        maxLevel,
        showTension,
        selectedChunk: nextSelectedChunk,
        relationEventId: null,
      }),
      { replace: true }
    );
  }, [currentTaskId, maxLevel, navigate, novelId, selectedNode, showTension]);

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

  if (!currentTaskId) {
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
            <Card variant="elevated" className="rounded-xl border-chart-negative/20">
              <CardContent className="flex items-start gap-3 p-4">
                <AlertTriangle className="mt-0.5 h-4 w-4 text-chart-negative" />
                <p className="text-sm text-text-muted">{selectionHint}</p>
              </CardContent>
            </Card>
          </motion.div>
        )}

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, delay: 0.1 }}
        >
          <Card variant="elevated" className="rounded-xl">
            <CardHeader className="pb-2">
              <CardTitle className="text-base font-semibold text-text">
                叙事结构 · 四阶段
              </CardTitle>
            </CardHeader>
            <CardContent>
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
            </CardContent>
          </Card>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, delay: 0.2 }}
        >
          <Card variant="elevated" className="rounded-xl">
            <CardHeader className="pb-2">
              <CardTitle className="text-base font-semibold text-text">
                叙事时间轴
              </CardTitle>
            </CardHeader>
            <CardContent>
              {isLoading ? (
                <div className="h-24 w-full animate-pulse rounded bg-surface-hover" />
              ) : isError ? (
                <div className="flex h-24 flex-col items-center justify-center gap-3 text-sm text-text-muted">
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
                <div className="flex h-24 items-center justify-center text-sm text-text-muted">
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
            </CardContent>
          </Card>
        </motion.div>

        {showTension && tensionCurve && tensionCurve.length > 0 && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3, delay: 0.3 }}
          >
            <Card variant="elevated" className="rounded-xl">
              <CardHeader className="pb-2">
                <CardTitle className="text-base font-semibold text-text">
                  张力曲线
                </CardTitle>
              </CardHeader>
              <CardContent>
                <TensionOverlay
                  tensionCurve={tensionCurve}
                  totalChunks={totalChunks}
                  height={120}
                />
              </CardContent>
            </Card>
          </motion.div>
        )}

        {novelId && (
          <TimelineNodeDetail
            node={selectedNode}
            novelId={novelId}
            taskId={currentTaskId}
            selectedRelationEventId={relationEventIdFromUrl}
            onClose={() => {
              navigate(
                buildTimelinePageUrl(novelId, currentTaskId, {
                  maxLevel,
                  showTension,
                  selectedChunk: null,
                  relationEventId: null,
                }),
                { replace: true }
              );
            }}
          />
        )}
      </div>
    </PageContainer>
  );
}
