import { useEffect, useState, useCallback } from "react";
import { useParams, useSearchParams, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { toast } from "sonner";
import { Loader2 } from "lucide-react";
import {
  getNarrativeStructure,
  getEmotionStats,
  getCharacterStats,
  getStyleStats,
  getTopics,
  getDiagnosis,
  getChunkCurves,
} from "@/api/results";
import { isDiagnosisRerunRequiredError } from "@/api/errorGuards";
import { getNovel } from "@/api/novels";
import {
  createAnalysisTask,
  resumeAnalysisTask,
  batchDeleteTasks,
  cancelAnalysisTask,
  getTaskStatus,
} from "@/api/analysis";
import { useNovelStore } from "@/store/novelStore";
import { useAnalysisStatus } from "@/hooks/useAnalysisStatus";
import { PageContainer } from "@/components/layout/PageContainer";
import { NovelHeader } from "@/components/common/NovelHeader";
import { DiagnosisSummaryCard } from "@/components/common/DiagnosisSummaryCard";
import { ScoreOverviewCard } from "@/components/common/ScoreOverviewCard";
import { DimensionMiniCard } from "@/components/common/DimensionMiniCard";
import { NarrativeStructureBar } from "@/components/common/NarrativeStructureBar";
import { MiniCurvePreview } from "@/components/charts/MiniCurvePreview";
import { AnalysisProgressPanel } from "@/components/analysis/AnalysisProgressPanel";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { hasCompleteFocusContract } from "@/lib/diagnosisContract";

const STALE_TIME = 5 * 60 * 1000;

function SkeletonGrid() {
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card className="h-[300px]">
          <CardContent className="p-5">
            <div className="space-y-4">
              <div className="h-5 w-24 animate-pulse rounded bg-surface-hover" />
              <div className="space-y-3">
                {Array.from({ length: 4 }).map((_, i) => (
                  <div key={i} className="flex gap-3">
                    <div className="h-4 w-4 animate-pulse rounded bg-surface-hover" />
                    <div className="h-4 flex-1 animate-pulse rounded bg-surface-hover" />
                  </div>
                ))}
              </div>
            </div>
          </CardContent>
        </Card>
        <Card className="h-[300px]">
          <CardContent className="p-5">
            <div className="space-y-4">
              <div className="h-5 w-24 animate-pulse rounded bg-surface-hover" />
              <div className="flex items-center gap-3">
                <div className="h-12 w-12 animate-pulse rounded-full bg-surface-hover" />
                <div className="space-y-2">
                  <div className="h-3 w-16 animate-pulse rounded bg-surface-hover" />
                  <div className="h-4 w-12 animate-pulse rounded bg-surface-hover" />
                </div>
              </div>
              <div className="space-y-2">
                {Array.from({ length: 3 }).map((_, i) => (
                  <div key={i} className="flex items-center justify-between">
                    <div className="h-3 w-16 animate-pulse rounded bg-surface-hover" />
                    <div className="h-3 w-20 animate-pulse rounded bg-surface-hover" />
                  </div>
                ))}
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
      <div className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-5">
        {Array.from({ length: 5 }).map((_, i) => (
          <Card key={i} className="h-[140px]" />
        ))}
      </div>
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card className="h-[200px]" />
        <Card className="h-[200px]" />
      </div>
    </div>
  );
}

function EmptyTaskPrompt({ onAnalyze, isAnalyzing }: {
  onAnalyze: () => void;
  isAnalyzing: boolean;
}) {
  return (
    <div className="flex h-96 flex-col items-center justify-center gap-4">
      <div className="flex h-16 w-16 items-center justify-center rounded-full bg-primary-subtle">
        <svg className="h-8 w-8 text-primary" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.325.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 0 1 1.37.49l1.296 2.247a1.125 1.125 0 0 1-.26 1.431l-1.003.827c-.293.241-.438.613-.43.992a7.723 7.723 0 0 1 0 .255c-.008.378.137.75.43.991l1.004.827c.424.35.534.955.26 1.43l-1.298 2.247a1.125 1.125 0 0 1-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 6.47 0 0 1-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.543-.56.94-1.11.94h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 0 1-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 0 1-1.369-.49l-1.297-2.247a1.125 1.125 0 0 1 .26-1.431l1.004-.827c.292-.24.437-.613.43-.991a6.932 6.932 0 0 1 0-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 1.125 0 0 1-.26-1.43l1.297-2.247a1.125 1.125 0 0 1 1.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.086.22-.128.332-.183.582-.495.644-.869l.214-1.28Z" />
          <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" />
        </svg>
      </div>
      <div className="text-center">
        <h3 className="text-lg font-semibold text-text">尚未分析</h3>
        <p className="mt-1 text-sm text-text-muted">
          点击下方按钮开始对这本小说进行量化分析
        </p>
      </div>
      <Button onClick={() => onAnalyze()} disabled={isAnalyzing}>
        {isAnalyzing && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
        {isAnalyzing ? "正在创建分析任务..." : "开始分析"}
      </Button>
    </div>
  );
}

function RerunRequiredState() {
  return (
    <div className="flex h-64 flex-col items-center justify-center gap-3 text-center">
      <p className="text-base font-semibold text-text">当前结果需要重新分析</p>
      <p className="text-sm text-text-muted">
        该任务的 diagnosis 焦点合同已失效，当前仪表盘结果不再可信，请重新分析后再查看。
      </p>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Main Component                                                    */
/* ------------------------------------------------------------------ */

export function NovelDetailPage() {
  const { novelId } = useParams<{ novelId: string }>();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { currentTaskId, setNovel, setTask } = useNovelStore();
  const [isStartingTask, setIsStartingTask] = useState(false);

  // 使用 useAnalysisStatus hook 进行轮询并同步进度到 store
  useAnalysisStatus(novelId ?? null, currentTaskId, {
    enabled: !!novelId && !!currentTaskId,
    onRunning: () => {
      setIsStartingTask(false);
    },
    onCompleted: () => {
      setIsStartingTask(false);
      toast.success("分析完成");
      // 刷新所有指标数据，确保仪表盘显示最新结果
      queryClient.invalidateQueries({ queryKey: ["metrics", novelId, currentTaskId] });
      queryClient.invalidateQueries({ queryKey: ["topics", novelId, currentTaskId] });
      queryClient.invalidateQueries({ queryKey: ["results", novelId, currentTaskId] });
    },
    onCancelled: () => {
      setIsStartingTask(false);
      toast.info("分析任务已取消");
    },
    onFailed: (error) => {
      setIsStartingTask(false);
      toast.error(`分析失败: ${error}`);
    },
  });

  const urlTaskId = searchParams.get("task_id");

  // Sync novelId to store on mount; initialize task from URL if present
  useEffect(() => {
    if (novelId) {
      setNovel(novelId);
      if (urlTaskId) {
        setTask(urlTaskId);
      }
    }
  }, [novelId, urlTaskId, setNovel, setTask]);

  // Reflect currentTaskId to URL for shareability
  useEffect(() => {
    if (!novelId) return;
    if (currentTaskId) {
      navigate(`/novels/${novelId}?task_id=${currentTaskId}`, { replace: true });
    } else {
      navigate(`/novels/${novelId}`, { replace: true });
    }
  }, [currentTaskId, novelId, navigate]);

  // Parallel data fetching
  const enabled = !!novelId && !!currentTaskId;
  const taskStatusQuery = useQuery({
    queryKey: ["task-status", novelId, currentTaskId],
    queryFn: () => getTaskStatus(novelId!, currentTaskId!),
    enabled,
    staleTime: 5 * 1000,
  });
  const taskStatus = taskStatusQuery.data?.status;
  const isTaskActivelyProcessing =
    taskStatus === "pending" || taskStatus === "running" || taskStatus === "cancelling";
  const canRequestResults = enabled && taskStatusQuery.isSuccess && !isTaskActivelyProcessing;
  const effectiveIsAnalyzing = isStartingTask || isTaskActivelyProcessing;
  const isTaskBusy = isStartingTask || isTaskActivelyProcessing;

  /** 创建任务并启动分析：调用 createAnalysisTask → 刷新任务列表 → 设置 taskId */
  const handleCreateTask = useCallback(async () => {
    if (!novelId || isTaskBusy) return;
    setIsStartingTask(true);
    try {
      const result = await createAnalysisTask(novelId);
      queryClient.invalidateQueries({ queryKey: ["tasks", novelId] });
      const newTaskId = result.task_id;
      setTask(newTaskId);
      toast.info("分析任务已创建，正在执行...");
    } catch {
      setIsStartingTask(false);
      toast.error("创建分析任务失败");
    }
  }, [novelId, isTaskBusy, queryClient, setTask]);

  /** 继续失败/待处理任务：调用 resumeAnalysisTask → 刷新任务列表 → 保持 task_id 不变 */
  const handleResumeTask = useCallback(async (taskId: string) => {
    if (!novelId || isTaskBusy) return;
    const normalizedTaskId = taskId.trim();
    if (!normalizedTaskId) return;
    setIsStartingTask(true);
    try {
      const result = await resumeAnalysisTask(novelId, normalizedTaskId);
      queryClient.invalidateQueries({ queryKey: ["tasks", novelId] });
      setTask(result.task_id);
      toast.info("继续分析任务已启动...");
    } catch {
      setIsStartingTask(false);
      toast.error("继续分析失败");
    }
  }, [novelId, isTaskBusy, queryClient, setTask]);

  const handleDeleteTask = useCallback(async () => {
    if (!novelId || !currentTaskId) return;
    if (!window.confirm("确定要删除当前分析任务吗？此操作不可恢复。")) return;
    try {
      const result = await batchDeleteTasks(novelId, [currentTaskId]);
      const deletedCurrentTask = result.deleted_ids.includes(currentTaskId);
      if (!deletedCurrentTask) {
        const reason = result.failed_ids[0]?.reason ?? result.message;
        toast.error(`删除任务失败: ${reason}`);
        return;
      }
      setTask(null);
      setIsStartingTask(false);
      queryClient.invalidateQueries({ queryKey: ["tasks", novelId] });
      toast.success("任务已删除");
    } catch {
      toast.error("删除任务失败");
    }
  }, [novelId, currentTaskId, setTask, queryClient]);

  const handleCancelTask = useCallback(async (taskId: string) => {
    if (!novelId) return;
    try {
      await cancelAnalysisTask(novelId, taskId);
      toast.success("任务取消请求已发送");
      queryClient.invalidateQueries({ queryKey: ["tasks", novelId] });
    } catch {
      toast.error("取消任务失败");
    }
  }, [novelId, queryClient]);

  // Fetch novel info for title
  const novelQuery = useQuery({
    queryKey: ["novel", novelId],
    queryFn: () => getNovel(novelId!),
    enabled: !!novelId,
    staleTime: 5 * 60 * 1000,
  });

  const narrativeQuery = useQuery({
    queryKey: ["metrics", novelId, currentTaskId, "narrative"],
    queryFn: () => getNarrativeStructure(novelId!, currentTaskId!),
    enabled: canRequestResults,
    staleTime: STALE_TIME,
  });

  const emotionQuery = useQuery({
    queryKey: ["metrics", novelId, currentTaskId, "emotion"],
    queryFn: () => getEmotionStats(novelId!, currentTaskId!),
    enabled: canRequestResults,
    staleTime: STALE_TIME,
  });

  const characterQuery = useQuery({
    queryKey: ["metrics", novelId, currentTaskId, "character"],
    queryFn: () => getCharacterStats(novelId!, currentTaskId!),
    enabled: canRequestResults,
    staleTime: STALE_TIME,
  });

  const styleQuery = useQuery({
    queryKey: ["metrics", novelId, currentTaskId, "style"],
    queryFn: () => getStyleStats(novelId!, currentTaskId!),
    enabled: canRequestResults,
    staleTime: STALE_TIME,
  });

  const topicsQuery = useQuery({
    queryKey: ["topics", novelId, currentTaskId],
    queryFn: () => getTopics(novelId!, currentTaskId!),
    enabled: canRequestResults,
    staleTime: STALE_TIME,
  });

  const diagnosisQuery = useQuery({
    queryKey: ["results", novelId, currentTaskId, "diagnosis"],
    queryFn: () => getDiagnosis(novelId!, currentTaskId!),
    enabled: canRequestResults,
    staleTime: STALE_TIME,
  });

  const curvesQuery = useQuery({
    queryKey: ["results", novelId, currentTaskId, "curves"],
    queryFn: () => getChunkCurves(novelId!, currentTaskId!),
    enabled: canRequestResults,
    staleTime: STALE_TIME,
  });

  const diagnosis = diagnosisQuery.data;
  const diagnosisRequiresRerun =
    diagnosisQuery.isSuccess &&
    diagnosis != null &&
    (diagnosis.rerun_required === true || !hasCompleteFocusContract(diagnosis));
  const isTopicsRerunError = isDiagnosisRerunRequiredError(topicsQuery.error);
  const hasDiagnosisLoaded = diagnosisQuery.isFetched && !diagnosisQuery.isError && !diagnosisRequiresRerun;

  const allMetricsLoaded =
    narrativeQuery.data &&
    emotionQuery.data &&
    characterQuery.data &&
    styleQuery.data &&
    topicsQuery.data &&
    hasDiagnosisLoaded;

  const isLoading =
    enabled &&
    (taskStatusQuery.isLoading ||
      (canRequestResults &&
        (narrativeQuery.isLoading ||
          emotionQuery.isLoading ||
          characterQuery.isLoading ||
          styleQuery.isLoading ||
          topicsQuery.isLoading ||
          diagnosisQuery.isLoading ||
          curvesQuery.isLoading)));

  // 首页对 rerun-required diagnosis 采用“单一重跑态”；
  // 依赖 diagnosis 的并行查询即便同时返回 409，也不应再额外叠加一层通用加载失败
  const hasAnyError =
    taskStatusQuery.isError ||
    narrativeQuery.isError ||
    emotionQuery.isError ||
    characterQuery.isError ||
    styleQuery.isError ||
    (topicsQuery.isError && !(diagnosisRequiresRerun && isTopicsRerunError)) ||
    diagnosisQuery.isError ||
    curvesQuery.isError;

  const retryAll = () => {
    taskStatusQuery.refetch();
    narrativeQuery.refetch();
    emotionQuery.refetch();
    characterQuery.refetch();
    styleQuery.refetch();
    topicsQuery.refetch();
    diagnosisQuery.refetch();
    curvesQuery.refetch();
  };

  // ---------- Render ----------

  return (
    <PageContainer className="px-5 py-4">
      {/* Header */}
      <NovelHeader
        title={novelQuery.data?.title ?? (novelId ? `小说 ${novelId.slice(0, 8)}` : "小说分析")}
        novelId={novelId}
        onCreateTask={handleCreateTask}
        onResumeTask={handleResumeTask}
        onDeleteCurrentTask={currentTaskId ? handleDeleteTask : undefined}
        isResuming={effectiveIsAnalyzing}
        className="mb-3"
      />

      {/* No task selected — offer start analysis */}
      {!currentTaskId && (
        <EmptyTaskPrompt onAnalyze={handleCreateTask} isAnalyzing={isStartingTask} />
      )}

      {/* Analysis in progress — show progress panel, hide everything else */}
      {effectiveIsAnalyzing && currentTaskId && (
        <motion.div className="flex min-h-0 flex-1 flex-col">
          <AnalysisProgressPanel
            taskId={currentTaskId}
            onCancel={() => handleCancelTask(currentTaskId)}
          />
        </motion.div>
      )}

      {/* Loading skeleton - only when not analyzing */}
      {!effectiveIsAnalyzing && isLoading && currentTaskId && <SkeletonGrid />}

      {/* Error state — only when not analyzing */}
      {!effectiveIsAnalyzing && hasAnyError && !isLoading && currentTaskId && (
        <div className="flex h-64 flex-col items-center justify-center gap-3">
          <p className="text-sm text-text-muted">数据加载失败</p>
          <Button variant="ghost" size="sm" onClick={retryAll}>
            重试
          </Button>
        </div>
      )}

      {!effectiveIsAnalyzing && diagnosisRequiresRerun && !isLoading && currentTaskId && <RerunRequiredState />}

      {/* Main content - only when not analyzing */}
      {!effectiveIsAnalyzing && allMetricsLoaded && !isLoading && currentTaskId && !diagnosisRequiresRerun && (
        <div className="space-y-4">
          {/* Row 1: 诊断画像 + 评分速览 */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.15 }}
            className="grid grid-cols-1 gap-4 lg:grid-cols-2"
          >
            {diagnosisQuery.data ? (
              <DiagnosisSummaryCard
                diagnosis={diagnosisQuery.data}
                novelId={novelId!}
                className="h-full"
              />
            ) : (
              <Card className="flex h-full items-center justify-center">
                <p className="text-sm text-text-muted">暂无诊断数据</p>
              </Card>
            )}

            <ScoreOverviewCard
              foreshadowExpectation={diagnosisQuery.data?.foreshadow_expectation}
              powerStance={diagnosisQuery.data?.power_stance_score}
              civilianDignity={diagnosisQuery.data?.common_people_dignity}
              culturalDepth={diagnosisQuery.data?.cultural_depth_score}
              novelId={novelId!}
              className="h-full"
            />
          </motion.div>

          {/* Row 2: 五维速览 */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.15, delay: 0.1 }}
            className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-5"
          >
            <DimensionMiniCard
              dimension="narrative"
              data={narrativeQuery.data ?? {}}
              novelId={novelId!}
              linkTo={`/novels/${novelId}/timeline`}
            />
            <DimensionMiniCard
              dimension="emotion"
              data={{
                pos_neg_ratio: emotionQuery.data?.pos_neg_ratio,
                positive_ratio: emotionQuery.data?.positive_ratio,
                negative_ratio: emotionQuery.data?.negative_ratio,
              }}
              novelId={novelId!}
              linkTo={`/novels/${novelId}/curves`}
            />
            <DimensionMiniCard
              dimension="character"
              data={characterQuery.data ?? {}}
              novelId={novelId!}
              linkTo={`/novels/${novelId}/graph`}
            />
            <DimensionMiniCard
              dimension="style"
              data={styleQuery.data ?? {}}
              novelId={novelId!}
            />
            <DimensionMiniCard
              dimension="topic"
              data={{
                topic_count: Array.isArray(topicsQuery.data) ? topicsQuery.data.length : 0,
                top_topics: Array.isArray(topicsQuery.data) ? topicsQuery.data.slice(0, 3).map(t => ({
                  words: t.words,
                  weight: t.weight,
                })) : [],
              }}
              novelId={novelId!}
              linkTo={`/novels/${novelId}/topics`}
            />
          </motion.div>

          {/* Row 3: 结构概览 + 曲线预览 */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.15, delay: 0.2 }}
            className="grid grid-cols-1 gap-4 lg:grid-cols-2"
          >
            <NarrativeStructureBar
              act1Ratio={narrativeQuery.data?.act1_ratio}
              act2Ratio={narrativeQuery.data?.act2_ratio}
              act3Ratio={narrativeQuery.data?.act3_ratio}
              eventDensity={narrativeQuery.data?.event_density}
              novelId={novelId!}
            />
            <MiniCurvePreview
              data={curvesQuery.data ?? []}
              novelId={novelId!}
            />
          </motion.div>
        </div>
      )}
    </PageContainer>
  );
}
