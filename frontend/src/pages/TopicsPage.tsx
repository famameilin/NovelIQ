/**
 * TopicsPage - 主题分布页面
 *
 * 创建时间: 2026-04-05
 * 创建者: GLM-5
 * 任务: Phase 2-C 主题分布
 * 说明: 展示 LDA 主题建模结果，包括词云、柱状图、表格
 */
import { useEffect, useMemo } from "react";
import { useParams, useSearchParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { getTopics, getDiagnosis } from "@/api/results";
import type { Topic } from "@/api/types";
import { useNovelStore } from "@/store/novelStore";
import { PageContainer } from "@/components/layout/PageContainer";
import { NovelHeader } from "@/components/common/NovelHeader";
import { Card, CardContent } from "@/components/ui/card";
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

export function TopicsPage() {
  const { novelId } = useParams<{ novelId: string }>();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { currentTaskId, setNovel, setTask } = useNovelStore();

  const urlTaskId = searchParams.get("task_id");

  useEffect(() => {
    if (novelId) {
      setNovel(novelId);
      if (urlTaskId) {
        setTask(urlTaskId);
      }
    }
  }, [novelId, urlTaskId, setNovel, setTask]);

  useEffect(() => {
    if (currentTaskId && urlTaskId !== currentTaskId) {
      navigate(`/novels/${novelId}/topics?task_id=${currentTaskId}`, { replace: true });
    }
  }, [currentTaskId, novelId, navigate, urlTaskId]);

  const enabled = !!novelId && !!currentTaskId;

  const topicsQuery = useQuery({
    queryKey: ["results", novelId, currentTaskId, "topics"],
    queryFn: () => getTopics(novelId!, currentTaskId!),
    enabled,
    staleTime: STALE_TIME,
  });

  // 获取诊断数据以融合 LLM 生成的主题命名（topic_labels）
  const diagnosisQuery = useQuery({
    queryKey: ["results", novelId, currentTaskId, "diagnosis"],
    queryFn: () => getDiagnosis(novelId!, currentTaskId!),
    enabled,
    staleTime: STALE_TIME,
  });

  const topicLabels = diagnosisQuery.data?.topic_labels;

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
  const isError = topicsQuery.isError || diagnosisQuery.isError;
  const errors = [topicsQuery.error, diagnosisQuery.error].filter(Boolean);
  const error = errors[0];

  const handleRetry = () => {
    topicsQuery.refetch();
    diagnosisQuery.refetch();
  };

  const renderContent = () => {
    if (!currentTaskId) {
      return (
        <motion.div variants={itemVariants}>
          <Card variant="elevated" className="rounded-xl">
            <CardContent className="flex flex-col items-center justify-center py-16">
              <AlertCircle className="h-12 w-12 text-text-muted mb-4" />
              <p className="text-lg font-medium text-text">请先选择分析任务</p>
              <p className="text-sm text-text-muted mt-2">
                在页面顶部选择一个任务后查看主题分布
              </p>
            </CardContent>
          </Card>
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
            <Card variant="elevated" className="rounded-xl">
              <CardContent className="p-5">
                <div className="h-6 w-24 bg-surface-hover rounded animate-pulse mb-4" />
                <div className="h-[300px] w-full bg-surface-hover rounded animate-pulse" />
              </CardContent>
            </Card>
          </motion.div>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <motion.div variants={itemVariants}>
              <Card variant="elevated" className="rounded-xl">
                <CardContent className="p-5">
                  <div className="h-6 w-24 bg-surface-hover rounded animate-pulse mb-4" />
                  <div className="h-[300px] w-full bg-surface-hover rounded animate-pulse" />
                </CardContent>
              </Card>
            </motion.div>
            <motion.div variants={itemVariants}>
              <Card variant="elevated" className="rounded-xl">
                <CardContent className="p-5">
                  <div className="h-6 w-24 bg-surface-hover rounded animate-pulse mb-4" />
                  <div className="h-[300px] w-full bg-surface-hover rounded animate-pulse" />
                </CardContent>
              </Card>
            </motion.div>
          </div>
        </motion.div>
      );
    }

    if (isError) {
      return (
        <motion.div variants={itemVariants}>
          <Card variant="elevated" className="rounded-xl">
            <CardContent className="flex flex-col items-center justify-center py-16">
              <AlertCircle className="h-12 w-12 text-chart-negative mb-4" />
              <p className="text-lg font-medium text-text">加载失败</p>
              <p className="text-sm text-text-muted mt-2 mb-4">
                {error instanceof Error ? error.message : "未知错误"}
                {errors.length > 1 && (
                  <span className="block text-xs mt-1 text-text-muted">
                    还有 {errors.length - 1} 个请求也失败了
                  </span>
                )}
              </p>
              <Button onClick={handleRetry} variant="outline">
                <RefreshCw className="h-4 w-4 mr-2" />
                重试
              </Button>
            </CardContent>
          </Card>
        </motion.div>
      );
    }

    if (topics.length === 0) {
      return (
        <motion.div variants={itemVariants}>
          <Card variant="elevated" className="rounded-xl">
            <CardContent className="flex flex-col items-center justify-center py-16">
              <AlertCircle className="h-12 w-12 text-text-muted mb-4" />
              <p className="text-lg font-medium text-text">暂无主题数据</p>
              <p className="text-sm text-text-muted mt-2">
                当前任务尚未生成主题分析结果
              </p>
            </CardContent>
          </Card>
        </motion.div>
      );
    }

    return (
      <div className="flex flex-col gap-4 flex-1 min-h-0">
        <TopicWordCloud topics={topics} maxWords={100} />

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 flex-1 min-h-0">
          <div className="h-full min-h-0">
            <TopicBarChart topics={topics} />
          </div>
          <div className="h-full min-h-0">
            <TopicTable topics={topics} />
          </div>
        </div>
      </div>
    );
  };

  return (
    <PageContainer className="flex flex-col">
      <NovelHeader title="主题分布" />

      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3 }}
        className="mt-4 flex flex-1 flex-col min-h-0"
      >
        {renderContent()}
      </motion.div>
    </PageContainer>
  );
}
