/**
 * TopicsPage - 主题分布页面
 *
 * 展示 LDA 主题建模结果，包括词云、柱状图、表格
 */
import { useEffect, useMemo } from "react";
import { useParams, useSearchParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { isAnalysisNotCompleteError, getAnalysisNotCompleteRunStatus } from "@/api/errorGuards";
import { getTopics, getDiagnosis } from "@/api/results";
import type { Topic } from "@/api/types";
import { useNovelScopedTask, shouldWriteBackTaskUrl } from "@/hooks/useNovelScopedTask";
import { AnalysisNotCompleteState } from "@/components/common/AnalysisNotCompleteState";
import { AnalysisWorkspace } from "@/components/layout/AnalysisWorkspace";
import { DashboardCardShell } from "@/components/common/DashboardCardShell";
import { Button } from "@/components/ui/button";
import {
  TopicWordCloud,
  TopicBarChart,
  TopicTable,
} from "@/components/topics";
import { RefreshCw, AlertCircle } from "lucide-react";

const STALE_TIME = 5 * 60 * 1000;

const containerVariants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: {
      staggerChildren: 0.1,
    },
  },
};

const itemVariants = {
  hidden: { opacity: 0, y: 20 },
  visible: { opacity: 1, y: 0 },
};

/**
 * 2026-04-28，任务：分析详情页单屏 Tabs 改造
 * 修改原因：主题页补齐统一工作区，并恢复为词云 + 权重/表格的单面板布局，避免三个 tab 过度拆散信息
 */
export function TopicsPage() {
  const { novelId } = useParams<{ novelId: string }>();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();

  const urlTaskId = searchParams.get("task_id");

  // 2026-08-13 P1-2: 小说作用域任务守卫——跨小说切换后旧小说的任务
  // 不得用于新小说的查询，也不得回写固化成新小说 URL（模式同 GraphPage）
  const { storeTaskId, urlTaskSyncRef } = useNovelScopedTask(novelId, urlTaskId);

  useEffect(() => {
    if (!novelId || !storeTaskId) return;
    if (!shouldWriteBackTaskUrl(urlTaskId, storeTaskId, urlTaskSyncRef)) return;
    navigate(`/novels/${novelId}/topics?task_id=${storeTaskId}`, { replace: true });
  }, [navigate, novelId, storeTaskId, urlTaskId, urlTaskSyncRef]);

  const enabled = !!novelId && !!storeTaskId;

  const topicsQuery = useQuery({
    queryKey: ["results", novelId, storeTaskId, "topics"],
    queryFn: () => getTopics(novelId!, storeTaskId!),
    enabled,
    staleTime: STALE_TIME,
  });

  // 获取诊断数据以融合 LLM 生成的主题命名（topic_labels）
  const diagnosisQuery = useQuery({
    queryKey: ["results", novelId, storeTaskId, "diagnosis"],
    queryFn: () => getDiagnosis(novelId!, storeTaskId!),
    enabled,
    staleTime: STALE_TIME,
  });

  const diagnosis = diagnosisQuery.data;
  const topicLabels = diagnosis?.topic_labels;

  const topics: Topic[] = useMemo(() => {
    const rawTopics = topicsQuery.data || [];
    if (!topicLabels || topicLabels.length === 0) return rawTopics;

    const labelMap = new Map<number, string>();
    topicLabels.forEach((label, idx) => {
      if (label) labelMap.set(idx, label);
    });

    return rawTopics.map((topic) => ({
      ...topic,
      label: topic.label ?? labelMap.get(topic.topic_id) ?? undefined,
    }));
  }, [topicsQuery.data, topicLabels]);

  const isLoading = topicsQuery.isLoading || diagnosisQuery.isLoading;
  const isAnalysisNotComplete =
    isAnalysisNotCompleteError(topicsQuery.error) || isAnalysisNotCompleteError(diagnosisQuery.error);
  const analysisFailed =
    getAnalysisNotCompleteRunStatus(topicsQuery.error) === "failed" ||
    getAnalysisNotCompleteRunStatus(diagnosisQuery.error) === "failed";
  const isError = (topicsQuery.isError || diagnosisQuery.isError) && !isAnalysisNotComplete;
  const errors = [topicsQuery.error, diagnosisQuery.error].filter(Boolean);
  const error = errors[0];

  const handleRetry = () => {
    topicsQuery.refetch();
    diagnosisQuery.refetch();
  };

  const renderContent = () => {
    if (!storeTaskId) {
      return (
        <motion.div variants={itemVariants}>
          <DashboardCardShell
            title="请先选择分析任务"
            icon={<AlertCircle className="h-4 w-4" />}
            accent="chart-2"
            className="min-h-[240px]"
            bodyClassName="items-center justify-center gap-2 text-center"
          >
            <AlertCircle className="h-12 w-12 text-text-muted" />
            <p className="text-sm text-text-muted">在页面顶部选择一个任务后查看主题分布。</p>
          </DashboardCardShell>
        </motion.div>
      );
    }

    if (isLoading) {
      return (
        <motion.div
          className="grid grid-cols-1 gap-6"
          variants={containerVariants}
          initial="hidden"
          animate="visible"
        >
          <motion.div variants={itemVariants}>
            <DashboardCardShell title="主题词云加载中" accent="chart-3">
              <div className="rounded-2xl border border-border/60 bg-surface/70 p-4">
                <div className="h-6 w-24 bg-surface-hover rounded animate-pulse mb-4" />
                <div className="h-[300px] w-full bg-surface-hover rounded animate-pulse" />
              </div>
            </DashboardCardShell>
          </motion.div>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <motion.div variants={itemVariants}>
              <DashboardCardShell title="主题权重加载中" accent="chart-2">
                <div className="rounded-2xl border border-border/60 bg-surface/70 p-4">
                  <div className="h-6 w-24 bg-surface-hover rounded animate-pulse mb-4" />
                  <div className="h-[300px] w-full bg-surface-hover rounded animate-pulse" />
                </div>
              </DashboardCardShell>
            </motion.div>
            <motion.div variants={itemVariants}>
              <DashboardCardShell title="主题表格加载中" accent="chart-4">
                <div className="rounded-2xl border border-border/60 bg-surface/70 p-4">
                  <div className="h-6 w-24 bg-surface-hover rounded animate-pulse mb-4" />
                  <div className="h-[300px] w-full bg-surface-hover rounded animate-pulse" />
                </div>
              </DashboardCardShell>
            </motion.div>
          </div>
        </motion.div>
      );
    }

    if (isAnalysisNotComplete) {
      return (
        <motion.div variants={itemVariants}>
          <AnalysisNotCompleteState
            title={analysisFailed ? "主题分析任务已失败" : "主题结果尚未完成"}
            description={
              analysisFailed
                ? "该分析任务已失败，主题结果无法读取，请重新发起分析后再查看。"
                : "当前任务仍在分析中，主题结果暂时不可读，请等待任务进入完成态后再查看。"
            }
            failed={analysisFailed}
          />
        </motion.div>
      );
    }

    if (isError) {
      return (
        <motion.div variants={itemVariants}>
          <DashboardCardShell
            title="主题分析加载失败"
            icon={<AlertCircle className="h-4 w-4" />}
            accent="chart-5"
            className="min-h-[240px]"
            bodyClassName="items-center justify-center gap-3 text-center"
          >
            <AlertCircle className="h-12 w-12 text-chart-negative" />
            <p className="text-sm text-text-muted">
              {error instanceof Error ? error.message : "未知错误"}
              {errors.length > 1 && (
                <span className="mt-1 block text-xs text-text-muted">
                  还有 {errors.length - 1} 个请求也失败了
                </span>
              )}
            </p>
            <Button onClick={handleRetry} variant="outline">
              <RefreshCw className="mr-2 h-4 w-4" />
              重试
            </Button>
          </DashboardCardShell>
        </motion.div>
      );
    }

    if (topics.length === 0) {
      return (
        <motion.div variants={itemVariants}>
          <DashboardCardShell
            title="暂无主题数据"
            icon={<AlertCircle className="h-4 w-4" />}
            accent="chart-4"
            className="min-h-[240px]"
            bodyClassName="items-center justify-center gap-2 text-center"
          >
            <AlertCircle className="h-12 w-12 text-text-muted" />
            <p className="text-sm text-text-muted">当前任务尚未生成主题分析结果。</p>
          </DashboardCardShell>
        </motion.div>
      );
    }

    return (
      <motion.div
        className="flex min-h-0 flex-1 flex-col gap-4"
        variants={containerVariants}
        initial="hidden"
        animate="visible"
      >
        <motion.div variants={itemVariants} className="min-h-0 flex-[1.15]">
          <TopicWordCloud topics={topics} maxWords={100} className="h-full" />
        </motion.div>

        <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 lg:grid-cols-2">
          <motion.div variants={itemVariants} className="min-h-0">
            <TopicBarChart topics={topics} className="h-full" />
          </motion.div>
          <motion.div variants={itemVariants} className="min-h-0">
            <TopicTable topics={topics} className="h-full" />
          </motion.div>
        </div>
      </motion.div>
    );
  };

  return (
    <AnalysisWorkspace title="主题分布">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3 }}
        className="flex min-h-0 flex-1 flex-col"
      >
        {renderContent()}
      </motion.div>
    </AnalysisWorkspace>
  );
}
