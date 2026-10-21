import { useEffect, useRef } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { isAxiosError } from "axios";
import { toast } from "sonner";
import { cancelAnalysisTask, resumeAnalysisTask } from "@/api/analysis";
import { getNovel } from "@/api/novels";
import { AnalysisProgressPanel } from "@/components/analysis/AnalysisProgressPanel";
import { PageContainer } from "@/components/layout/PageContainer";
import { Button } from "@/components/ui/button";
import { useAnalysisStatus } from "@/hooks/useAnalysisStatus";
import { useNovelScopedTask } from "@/hooks/useNovelScopedTask";
import { analysisTaskPath, novelTaskPath } from "@/lib/analysisTaskRoutes";
import { useStreamStore } from "@/store/streamStore";

/** 承载未完成任务，最终通知同步后自动切换到同一任务结果 */
export function AnalysisTaskPage() {
  const { novelId, taskId } = useParams<{ novelId: string; taskId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const epoch = useStreamStore(state => state.resumeEpoch);
  const openedEpoch = useRef(0);
  useNovelScopedTask(novelId, taskId ?? null);
  useEffect(() => {
    useStreamStore.getState().resetStreamForTask(taskId ?? null);
    openedEpoch.current = useStreamStore.getState().resumeEpoch;
  }, [novelId, taskId]);
  const analysis = useAnalysisStatus(novelId ?? null, taskId ?? null, {
    onCompleted: () => {
      queryClient.invalidateQueries({ queryKey: ["tabs", novelId, taskId] });
      toast.success("分析完成");
    },
    onCancelled: () => toast.info("分析任务已停止"),
    onFailed: error => toast.error(`分析失败: ${error}`),
  });
  useEffect(() => {
    if (epoch < openedEpoch.current || !novelId || !taskId || analysis.query.isError) return;
    if (analysis.status === "completed" && analysis.projectionSynced) {
      navigate(novelTaskPath(novelId, taskId), {replace: true});
    }
  }, [epoch, novelId, taskId, analysis.status, analysis.projectionSynced, analysis.query.isError, navigate]);
  const novel = useQuery({
    queryKey: ["novel", novelId], queryFn: () => getNovel(novelId!),
    enabled: !!novelId, staleTime: 5 * 60 * 1000,
  });
  const missing = isAxiosError(analysis.query.error) && analysis.query.error.response?.status === 404;
  const cancel = async () => {
    if (!novelId || !taskId) return;
    try {
      await cancelAnalysisTask(novelId, taskId);
      queryClient.invalidateQueries({ queryKey: ["task-status", novelId, taskId] });
      queryClient.invalidateQueries({ queryKey: ["tasks", novelId] });
      toast.info("任务取消请求已发送");
    } catch {
      toast.error("取消任务失败");
    }
  };
  const resume = async () => {
    if (!novelId || !taskId) return;
    try {
      const result = await resumeAnalysisTask(novelId, taskId);
      queryClient.invalidateQueries({ queryKey: ["task-status", novelId, result.task_id] });
      queryClient.invalidateQueries({ queryKey: ["tasks", novelId] });
      useStreamStore.getState().resetStreamForTask(result.task_id);
      if (result.task_id !== taskId) navigate(analysisTaskPath(novelId, result.task_id), { replace: true });
      toast.info("继续分析任务已启动");
    } catch {
      toast.error("继续分析失败");
    }
  };

  return <PageContainer className="h-auto min-h-full max-w-full px-5 py-4">
    <div className="mb-5 flex items-center justify-between gap-5">
      <h1 className="text-xl font-semibold text-text">{novel.data?.title ?? "小说"} · 分析任务详情</h1>
    </div>
    {analysis.query.isError ? <div className="rounded-xl border border-border bg-surface p-8" role="alert">
      <p className="text-text">{missing ? "分析任务不存在或不属于当前小说" : "无法读取分析任务状态"}</p>
      <Button className="mt-4" variant="outline" onClick={() => analysis.query.refetch()}>重试</Button>
    </div> : <AnalysisProgressPanel key={taskId} taskId={taskId!} onCancel={cancel} onResume={resume} />}
  </PageContainer>;
}
