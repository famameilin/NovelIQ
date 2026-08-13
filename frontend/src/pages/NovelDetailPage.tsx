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
import { isDiagnosisRerunRequiredError, isAnalysisNotCompleteError, getAnalysisNotCompleteRunStatus } from "@/api/errorGuards";
import { getNovel } from "@/api/novels";
import {
  createAnalysisTask,
  resumeAnalysisTask,
  batchDeleteTasks,
  cancelAnalysisTask,
  getTaskStatus,
} from "@/api/analysis";
import { useNovelStore } from "@/store/novelStore";
import { useNovelScopedTask, shouldWriteBackTaskUrl } from "@/hooks/useNovelScopedTask";
import { useAnalysisStatus } from "@/hooks/useAnalysisStatus";
import { AnalysisWorkspace } from "@/components/layout/AnalysisWorkspace";
import { AnalysisNotCompleteState } from "@/components/common/AnalysisNotCompleteState";
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

/**
 * 2026-04-28，任务：分析详情页单屏 Tabs 改造
 * 修改原因：仪表盘页补齐统一单屏工作区，后续模块统一走共享布局边界
 *
 * 2026-04-29，任务：仪表盘收口
 * 修改原因：仪表盘不再拆成两个 tab，结构与曲线预览直接并回同一面板，减少无意义切换
 */
export function NovelDetailPage() {
  const { novelId } = useParams<{ novelId: string }>();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { currentTaskId, setTask } = useNovelStore();
  const [isStartingTask, setIsStartingTask] = useState(false);

  const urlTaskId = searchParams.get("task_id");

  // 2026-08-13 P1-2: 小说作用域任务守卫——跨小说切换后 store 中旧小说的任务
  // 不得用于新小说的 SSE/查询，也不得回写固化成新小说 URL（模式同 GraphPage）
  const { storeTaskId, urlTaskSyncRef } = useNovelScopedTask(novelId, urlTaskId);

  // 使用 useAnalysisStatus hook 进行轮询并同步进度到 store
  useAnalysisStatus(novelId ?? null, storeTaskId, {
    enabled: !!novelId && !!storeTaskId,
    onRunning: () => {
      setIsStartingTask(false);
    },
    onCompleted: () => {
      setIsStartingTask(false);
      toast.success("分析完成");
      // 刷新所有指标数据，确保仪表盘显示最新结果
      queryClient.invalidateQueries({ queryKey: ["metrics", novelId, storeTaskId] });
      queryClient.invalidateQueries({ queryKey: ["topics", novelId, storeTaskId] });
      queryClient.invalidateQueries({ queryKey: ["results", novelId, storeTaskId] });
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

  // 把 store 的当前任务反映到 URL，方便分享与刷新恢复；
  // 2026-08-13 P1-2: URL 写回同样加小说作用域守卫——跨小说切换瞬间
  // 旧小说的 task_id 不得固化成新小说 URL；URL 上尚未同步进 store 的
  // deep-link 也不得被旧 store 状态抢先覆盖（GraphPage/TimelinePage 同款机制）
  useEffect(() => {
    if (!novelId) return;
    if (!storeTaskId) {
      // 任务已被删除/尚未选择：清掉 URL 上残留的 task_id；
      // 若 URL 上的 task_id 还是未同步的 deep-link，则等待同步后再处理
      if (urlTaskId && urlTaskSyncRef.current === urlTaskId) {
        return;
      }
      navigate(`/novels/${novelId}`, { replace: true });
      return;
    }
    if (!shouldWriteBackTaskUrl(urlTaskId, storeTaskId, urlTaskSyncRef)) {
      return;
    }
    navigate(`/novels/${novelId}?task_id=${storeTaskId}`, { replace: true });
  }, [navigate, novelId, storeTaskId, urlTaskId, urlTaskSyncRef]);

  // 并行拉取数据
  const enabled = !!novelId && !!storeTaskId;
  const taskStatusQuery = useQuery({
    queryKey: ["task-status", novelId, storeTaskId],
    queryFn: () => getTaskStatus(novelId!, storeTaskId!),
    enabled,
    staleTime: 5 * 1000,
    // 2026-08-08 用于让 resume 后的任务自动进入进度态：
    // taskId 不变时 queryKey 不变化，缓存会停留在旧终态（如 cancelled），
    // 活跃期每 3 秒轮询一次，终态后停止轮询
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "pending" || status === "running" || status === "cancelling" ? 3000 : false;
    },
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

  /** 继续失败/待处理/已取消任务：调用 resumeAnalysisTask → 刷新任务列表与状态 → 保持 task_id 不变 */
  const handleResumeTask = useCallback(async (taskId: string) => {
    if (!novelId || isTaskBusy) return;
    const normalizedTaskId = taskId.trim();
    if (!normalizedTaskId) return;
    setIsStartingTask(true);
    try {
      const result = await resumeAnalysisTask(novelId, normalizedTaskId);
      queryClient.invalidateQueries({ queryKey: ["tasks", novelId] });
      queryClient.invalidateQueries({ queryKey: ["task-status", novelId, normalizedTaskId] });
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

  // 拉取小说信息用于展示标题
  const novelQuery = useQuery({
    queryKey: ["novel", novelId],
    queryFn: () => getNovel(novelId!),
    enabled: !!novelId,
    staleTime: 5 * 60 * 1000,
  });

  const narrativeQuery = useQuery({
    queryKey: ["metrics", novelId, storeTaskId, "narrative"],
    queryFn: () => getNarrativeStructure(novelId!, storeTaskId!),
    enabled: canRequestResults,
    staleTime: STALE_TIME,
  });

  const emotionQuery = useQuery({
    queryKey: ["metrics", novelId, storeTaskId, "emotion"],
    queryFn: () => getEmotionStats(novelId!, storeTaskId!),
    enabled: canRequestResults,
    staleTime: STALE_TIME,
  });

  const characterQuery = useQuery({
    queryKey: ["metrics", novelId, storeTaskId, "character"],
    queryFn: () => getCharacterStats(novelId!, storeTaskId!),
    enabled: canRequestResults,
    staleTime: STALE_TIME,
  });

  const styleQuery = useQuery({
    queryKey: ["metrics", novelId, storeTaskId, "style"],
    queryFn: () => getStyleStats(novelId!, storeTaskId!),
    enabled: canRequestResults,
    staleTime: STALE_TIME,
  });

  const topicsQuery = useQuery({
    queryKey: ["topics", novelId, storeTaskId],
    queryFn: () => getTopics(novelId!, storeTaskId!),
    enabled: canRequestResults,
    staleTime: STALE_TIME,
  });

  const diagnosisQuery = useQuery({
    queryKey: ["results", novelId, storeTaskId, "diagnosis"],
    queryFn: () => getDiagnosis(novelId!, storeTaskId!),
    enabled: canRequestResults,
    staleTime: STALE_TIME,
  });

  const curvesQuery = useQuery({
    queryKey: ["results", novelId, storeTaskId, "curves"],
    queryFn: () => getChunkCurves(novelId!, storeTaskId!),
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

  const resultQueryErrors = [
    narrativeQuery.error,
    emotionQuery.error,
    characterQuery.error,
    styleQuery.error,
    topicsQuery.error,
    diagnosisQuery.error,
    curvesQuery.error,
  ];
  const analysisNotComplete = resultQueryErrors.some(isAnalysisNotCompleteError);
  const analysisFailed = resultQueryErrors.some(
    (error) => getAnalysisNotCompleteRunStatus(error) === "failed"
  );

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

  // ---------- 渲染 ----------

  return (
    <AnalysisWorkspace
      title={novelQuery.data?.title ?? (novelId ? `小说 ${novelId.slice(0, 8)}` : "小说分析")}
      headerProps={{
        novelId,
        onCreateTask: handleCreateTask,
        onResumeTask: handleResumeTask,
        onDeleteCurrentTask: storeTaskId ? handleDeleteTask : undefined,
        isResuming: effectiveIsAnalyzing,
      }}
      className="px-5"
      headerClassName="mb-3"
    >
      {/*
        2026-04-29，任务：仪表盘收口
        修改原因：仪表盘仍走 tabs 公共工作区，但只保留一个 tab，统一和其他分析页的边距与面板语义。
      */}

      {/* 未选择任务时，提示开始分析 */}
      {!storeTaskId && (
        <EmptyTaskPrompt onAnalyze={handleCreateTask} isAnalyzing={isStartingTask} />
      )}

      {/* 分析进行中时，只显示进度面板并隐藏其他内容 */}
      {effectiveIsAnalyzing && storeTaskId && (
        <motion.div className="flex min-h-0 flex-1 flex-col">
          <AnalysisProgressPanel
            taskId={storeTaskId}
            onCancel={() => handleCancelTask(storeTaskId)}
          />
        </motion.div>
      )}

      {/* 仅在未分析中时显示加载骨架屏 */}
      {!effectiveIsAnalyzing && isLoading && storeTaskId && <SkeletonGrid />}

      {/* 仅在未分析中时显示错误状态 */}
      {!effectiveIsAnalyzing && analysisNotComplete && !isLoading && storeTaskId && (
        <AnalysisNotCompleteState
          title={analysisFailed ? "分析任务已失败" : "分析尚未完成"}
          description={
            analysisFailed
              ? "该分析任务已失败，结果无法读取，请重新发起分析后再查看。"
              : "当前任务仍在分析中，结果暂时不可读，请等待任务进入完成态后再查看。"
          }
          failed={analysisFailed}
        />
      )}

      {/* 仅在未分析中时显示其他错误状态 */}
      {!effectiveIsAnalyzing && hasAnyError && !analysisNotComplete && !isLoading && storeTaskId && (
        <div className="flex h-64 flex-col items-center justify-center gap-3">
          <p className="text-sm text-text-muted">数据加载失败</p>
          <Button variant="ghost" size="sm" onClick={retryAll}>
            重试
          </Button>
        </div>
      )}

      {!effectiveIsAnalyzing && diagnosisRequiresRerun && !isLoading && storeTaskId && <RerunRequiredState />}

      {/* 仅在未分析中时显示主内容 */}
      {!effectiveIsAnalyzing && allMetricsLoaded && !isLoading && storeTaskId && !diagnosisRequiresRerun && (
        <AnalysisWorkspace.Tabs defaultValue="dashboard">
          <AnalysisWorkspace.Tab value="dashboard" label="仪表盘">
            <div className="grid h-full min-h-0 grid-rows-[auto_auto_minmax(0,1fr)] gap-3">
              <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
                {diagnosisQuery.data ? (
                  <DiagnosisSummaryCard diagnosis={diagnosisQuery.data} novelId={novelId!} className="h-full min-h-0" />
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
                  className="h-full min-h-0"
                />
              </div>

              <div className="grid grid-cols-2 gap-2.5 md:grid-cols-3 lg:grid-cols-5">
                <DimensionMiniCard dimension="narrative" data={narrativeQuery.data ?? {}} novelId={novelId!} linkTo={`/novels/${novelId}/timeline`} className="min-h-0" />
                <DimensionMiniCard
                  dimension="emotion"
                  data={{
                    pos_neg_ratio: emotionQuery.data?.pos_neg_ratio,
                    positive_ratio: emotionQuery.data?.positive_ratio,
                    negative_ratio: emotionQuery.data?.negative_ratio,
                  }}
                  novelId={novelId!}
                  linkTo={`/novels/${novelId}/curves`}
                  className="min-h-0"
                />
                <DimensionMiniCard dimension="character" data={characterQuery.data ?? {}} novelId={novelId!} linkTo={`/novels/${novelId}/graph`} className="min-h-0" />
                <DimensionMiniCard dimension="style" data={styleQuery.data ?? {}} novelId={novelId!} className="min-h-0" />
                <DimensionMiniCard
                  dimension="topic"
                  data={{
                    topic_count: Array.isArray(topicsQuery.data) ? topicsQuery.data.length : 0,
                    top_topics: Array.isArray(topicsQuery.data)
                      ? topicsQuery.data.slice(0, 3).map((t) => ({
                          words: t.words,
                          weight: t.weight,
                        }))
                      : [],
                  }}
                  novelId={novelId!}
                  linkTo={`/novels/${novelId}/topics`}
                  className="min-h-0"
                />
              </div>

              <div className="grid min-h-0 grid-cols-1 gap-3 lg:grid-cols-2">
                <NarrativeStructureBar
                  act1Ratio={narrativeQuery.data?.act1_ratio}
                  act2Ratio={narrativeQuery.data?.act2_ratio}
                  act3Ratio={narrativeQuery.data?.act3_ratio}
                  eventDensity={narrativeQuery.data?.event_density}
                  novelId={novelId!}
                  className="h-full min-h-0"
                />
                <MiniCurvePreview data={curvesQuery.data ?? []} novelId={novelId!} className="h-full min-h-0" />
              </div>
            </div>
          </AnalysisWorkspace.Tab>
        </AnalysisWorkspace.Tabs>
      )}
    </AnalysisWorkspace>
  );
}
