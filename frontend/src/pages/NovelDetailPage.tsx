import { useEffect, useState, useCallback } from "react";
import { useParams, useSearchParams, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { toast } from "sonner";
import { Loader2 } from "lucide-react";
import {
  createAnalysisTask,
  resumeAnalysisTask,
  batchDeleteTasks,
} from "@/api/analysis";
import { getDashboardTab, tabQueryKey } from "@/api/tabs";
import { isAnalysisNotCompleteError, getAnalysisNotCompleteRunStatus } from "@/api/errorGuards";
import { getNovel } from "@/api/novels";
import { useNovelStore } from "@/store/novelStore";
import { useStreamStore } from "@/store/streamStore";
import { useNovelScopedTask } from "@/hooks/useNovelScopedTask";
import { useAnalysisStatus } from "@/hooks/useAnalysisStatus";
import { AnalysisWorkspace } from "@/components/layout/AnalysisWorkspace";
import { AnalysisNotCompleteState } from "@/components/common/AnalysisNotCompleteState";
import { DiagnosisSummaryCard } from "@/components/common/DiagnosisSummaryCard";
import { ScoreOverviewCard } from "@/components/common/ScoreOverviewCard";
import { DimensionMiniCard } from "@/components/common/DimensionMiniCard";
import { NarrativeStructureBar } from "@/components/common/NarrativeStructureBar";
import { MiniCurvePreview } from "@/components/charts/MiniCurvePreview";
import { analysisTaskPath } from "@/lib/analysisTaskRoutes";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

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
        <h3 className="text-lg font-semibold text-text">选择任务或开始分析</h3>
        <p className="mt-1 text-sm text-text-muted">
          从上方选择已有任务，或开始一次新的量化分析
        </p>
      </div>
      <Button onClick={() => onAnalyze()} disabled={isAnalyzing}>
        {isAnalyzing && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
        {isAnalyzing ? "正在创建分析任务..." : "开始分析"}
      </Button>
    </div>
  );
}

/**
 * 仪表盘页使用共享单屏工作区布局
 *
 * 仪表盘不拆 tab，结构与曲线预览放在同一面板
 */
export function NovelDetailPage() {
  const { novelId } = useParams<{ novelId: string }>();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { currentTaskId, setTask } = useNovelStore();
  const [isStartingTask, setIsStartingTask] = useState(false);

  const urlTaskId = searchParams.get("task_id");

  // 小说作用域任务守卫——跨小说切换后 store 中旧小说的任务
  // 不得用于新小说的 SSE/查询，也不得回写固化成新小说 URL（模式同 GraphPage）
  const { storeTaskId: scopedTaskId, urlTaskSyncRef } = useNovelScopedTask(novelId, urlTaskId);
  const storeTaskId = urlTaskId && scopedTaskId === urlTaskId ? scopedTaskId : null;

  // 使用 useAnalysisStatus hook 进行轮询并同步进度到 store
  const analysis = useAnalysisStatus(novelId ?? null, storeTaskId, {
    enabled: !!novelId && !!storeTaskId,
    onRunning: () => {
      setIsStartingTask(false);
    },
    onCompleted: () => {
      setIsStartingTask(false);
      toast.success("分析完成");
      // 刷新所有 tab 级数据，确保仪表盘显示最新结果
      queryClient.invalidateQueries({ queryKey: ["tabs", novelId, storeTaskId] });
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

  // 无任务地址保留选择入口，明确指定的任务按实际状态分流
  useEffect(() => {
    if (!novelId || !urlTaskId) return;
    if (scopedTaskId !== urlTaskId && urlTaskSyncRef.current === urlTaskId) return;
    if (!scopedTaskId) {
      navigate(`/novels/${novelId}`, { replace: true });
      return;
    }
    if (scopedTaskId !== urlTaskId) return;
    urlTaskSyncRef.current = null;
    if (analysis.status && analysis.status !== "completed" && !analysis.query.isError) {
      navigate(analysisTaskPath(novelId, scopedTaskId), {replace: true});
    }
  }, [navigate, novelId, scopedTaskId, urlTaskId, urlTaskSyncRef, analysis.status, analysis.query.isError]);

  // 并行拉取数据
  const enabled = !!novelId && !!storeTaskId;
  const taskStatusQuery = analysis.query;
  const taskStatus = analysis.status;
  const isTaskActivelyProcessing =
    taskStatus === "pending" || taskStatus === "running" || taskStatus === "cancelling";
  const canRequestResults = enabled && taskStatus === "completed" && analysis.projectionSynced;
  const showTaskSummary = !!storeTaskId && !canRequestResults;
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
      navigate(analysisTaskPath(novelId, newTaskId));
    } catch {
      setIsStartingTask(false);
      toast.error("创建分析任务失败");
    }
  }, [novelId, isTaskBusy, queryClient, setTask, navigate]);

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
      // 恢复后重新订阅快照，保留已选执行的详情
      useStreamStore.getState().resetStreamForTask(result.task_id);
      setTask(result.task_id);
      toast.info("继续分析任务已启动...");
      navigate(analysisTaskPath(novelId, result.task_id));
    } catch {
      setIsStartingTask(false);
      toast.error("继续分析失败");
    }
  }, [novelId, isTaskBusy, queryClient, setTask, navigate]);

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

  // 拉取小说信息用于展示标题
  const novelQuery = useQuery({
    queryKey: ["novel", novelId],
    queryFn: () => getNovel(novelId!),
    enabled: !!novelId,
    staleTime: 5 * 60 * 1000,
  });

  // 仪表盘 tab：一次拉取全部八段复合数据
  const dashboardQuery = useQuery({
    queryKey: tabQueryKey("dashboard", novelId, storeTaskId),
    queryFn: () => getDashboardTab(novelId!, storeTaskId!),
    enabled: canRequestResults,
    staleTime: STALE_TIME,
  });
  const dashboard = dashboardQuery.data;

  const isLoading =
    enabled &&
    (taskStatusQuery.isLoading || (canRequestResults && dashboardQuery.isLoading));

  // 首页对 rerun-required diagnosis 采用“单一重跑态”；
  // tab 响应中的 diagnosis 为 null 时按“暂无诊断数据”展示
  const hasAnyError = taskStatusQuery.isError || dashboardQuery.isError;
  const analysisNotComplete = isAnalysisNotCompleteError(dashboardQuery.error);
  const analysisFailed = getAnalysisNotCompleteRunStatus(dashboardQuery.error) === "failed";

  const retryAll = () => {
    taskStatusQuery.refetch();
    dashboardQuery.refetch();
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

      {/* 未选择任务时，提示开始分析 */}
      {!storeTaskId && (
        <EmptyTaskPrompt onAnalyze={handleCreateTask} isAnalyzing={isStartingTask} />
      )}

      {/* 状态核对与通知同步期间保持结果门禁 */}
      {showTaskSummary && storeTaskId && (
        <motion.div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-4">
          <h2 className="text-lg font-medium text-text">{taskStatusQuery.isError ? "任务状态读取失败" : taskStatus === "completed" ? "正在同步最终执行记录" : "正在核对任务状态"}</h2>
          {taskStatusQuery.isError && <Button variant="outline" onClick={() => taskStatusQuery.refetch()}>重试</Button>}
        </motion.div>
      )}

      {/* 仅在未分析中时显示加载骨架屏 */}
      {!showTaskSummary && isLoading && storeTaskId && <SkeletonGrid />}

      {/* 仅在未分析中时显示错误状态 */}
      {!showTaskSummary && analysisNotComplete && !isLoading && storeTaskId && (
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
      {!showTaskSummary && hasAnyError && !analysisNotComplete && !isLoading && storeTaskId && (
        <div className="flex h-64 flex-col items-center justify-center gap-3">
          <p className="text-sm text-text-muted">数据加载失败</p>
          <Button variant="ghost" size="sm" onClick={retryAll}>
            重试
          </Button>
        </div>
      )}

      {/* 仅在未分析中时显示主内容 */}
      {!showTaskSummary && dashboard && !isLoading && storeTaskId && (
        <AnalysisWorkspace.Tabs defaultValue="dashboard">
          <AnalysisWorkspace.Tab value="dashboard" label="仪表盘">
            <div className="h-full min-h-0 overflow-y-auto pr-1">
              <div className="grid min-h-full grid-rows-[auto_auto_auto] gap-3 pb-1">
              <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
                {dashboard.diagnosis ? (
                  <DiagnosisSummaryCard diagnosis={dashboard.diagnosis} novelId={novelId!} className="h-full min-h-0" />
                ) : (
                  <Card className="flex h-full items-center justify-center">
                    <p className="text-sm text-text-muted">暂无诊断数据</p>
                  </Card>
                )}

                <ScoreOverviewCard
                  foreshadowExpectation={dashboard.diagnosis?.foreshadow_expectation}
                  powerStance={dashboard.diagnosis?.power_stance_score}
                  civilianDignity={dashboard.diagnosis?.common_people_dignity}
                  culturalDepth={dashboard.diagnosis?.cultural_depth_score}
                  novelId={novelId!}
                  className="h-full min-h-0"
                />
              </div>

              <div className="grid grid-cols-2 gap-2.5 md:grid-cols-3 lg:grid-cols-5">
                <DimensionMiniCard dimension="narrative" data={dashboard.narrative_structure ?? {}} novelId={novelId!} linkTo={`/novels/${novelId}/timeline`} className="min-h-0" />
                <DimensionMiniCard
                  dimension="emotion"
                  data={{
                    lexical_positive_density: dashboard.chapter_metrics?.book.pos_density,
                    lexical_negative_density: dashboard.chapter_metrics?.book.neg_density,
                  }}
                  novelId={novelId!}
                  linkTo={`/novels/${novelId}/curves`}
                  className="min-h-0"
                />
                <DimensionMiniCard dimension="character" data={dashboard.character_stats ?? {}} novelId={novelId!} linkTo={`/novels/${novelId}/graph`} className="min-h-0" />
                <DimensionMiniCard
                  dimension="style"
                  data={{
                    string_token_diversity: dashboard.style_stats?.string_token_diversity,
                    dialogue_ratio: dashboard.style_stats?.dialogue_ratio,
                  }}
                  novelId={novelId!}
                  className="min-h-0"
                />
                <DimensionMiniCard
                  dimension="topic"
                  data={{
                    topic_count: dashboard.topics.length,
                    top_topics: dashboard.topics.slice(0, 3).map((t) => ({
                      words: t.words,
                      weight: t.weight,
                    })),
                  }}
                  novelId={novelId!}
                  linkTo={`/novels/${novelId}/topics`}
                  className="min-h-0"
                />
              </div>

              <div className="grid min-h-0 grid-cols-1 gap-3 lg:grid-cols-2">
                <NarrativeStructureBar
                  act1Ratio={dashboard.narrative_structure?.act1_ratio}
                  act2Ratio={dashboard.narrative_structure?.act2_ratio}
                  act3Ratio={dashboard.narrative_structure?.act3_ratio}
                  chapterNarrativeFunctionShare={dashboard.narrative_structure?.chapter_narrative_function_share}
                  novelId={novelId!}
                  className="h-full min-h-0"
                />
                <MiniCurvePreview data={dashboard.emotion_trend} novelId={novelId!} className="h-full min-h-0" />
              </div>
              </div>
            </div>
          </AnalysisWorkspace.Tab>
        </AnalysisWorkspace.Tabs>
      )}
    </AnalysisWorkspace>
  );
}
