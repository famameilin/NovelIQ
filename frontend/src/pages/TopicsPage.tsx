/**
 * TopicsPage - 主题分布页面（2026-08-29 tab 级 API 统一）
 *
 * 四个 tab，每 tab 一个 API：
 * - 主题总览  → GET /tabs/topics-overview（主题词 + 全书/章节完整分布 + TextRank 关键词 + 诊断标签）
 * - 主题演进  → GET /topics/series（段落完整 K 维堆积面积图）
 * - 主题迁移  → GET /topics/shifts（JS 散度滑窗候选点）
 * - 主题情绪  → GET /topics/emotion（主题净情绪关联）
 */
import { useEffect, useMemo } from "react";
import type { ReactNode } from "react";
import { useParams, useSearchParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import type { UseQueryResult } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { isAnalysisNotCompleteError, getAnalysisNotCompleteRunStatus } from "@/api/errorGuards";
import { getTopicSeries, getTopicShifts, getTopicEmotion } from "@/api/results";
import { getTopicsOverviewTab, tabQueryKey } from "@/api/tabs";
import { useNovelScopedTask, shouldWriteBackTaskUrl } from "@/hooks/useNovelScopedTask";
import { AnalysisNotCompleteState } from "@/components/common/AnalysisNotCompleteState";
import { TabUnavailableState } from "@/components/common/TabUnavailableState";
import { AnalysisWorkspace } from "@/components/layout/AnalysisWorkspace";
import { DashboardCardShell } from "@/components/common/DashboardCardShell";
import { Button } from "@/components/ui/button";
import {
  TopicWordCloud,
  TopicBarChart,
  TopicTable,
  TopicDistributionChart,
  TopicKeywordsCard,
  TopicSeriesChart,
  TopicShiftsPanel,
  TopicEmotionPanel,
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

/** 单 tab 的加载/错误态统一门禁：通过后渲染数据内容 */
function renderTabGate<T>(
  query: UseQueryResult<T>,
  title: string,
  unavailableReason: string | null | undefined,
  content: (data: T) => ReactNode,
): ReactNode {
  if (query.isLoading) {
    return (
      <DashboardCardShell title={`${title}加载中`} accent="chart-3">
        <div className="h-[320px] w-full animate-pulse rounded bg-surface-hover" />
      </DashboardCardShell>
    );
  }
  if (isAnalysisNotCompleteError(query.error)) {
    const failed = getAnalysisNotCompleteRunStatus(query.error) === "failed";
    return (
      <AnalysisNotCompleteState
        title={failed ? "主题分析任务已失败" : "主题结果尚未完成"}
        description={
          failed
            ? "该分析任务已失败，主题结果无法读取，请重新发起分析后再查看。"
            : "当前任务仍在分析中，主题结果暂时不可读，请等待任务进入完成态后再查看。"
        }
        failed={failed}
      />
    );
  }
  if (query.isError) {
    return (
      <DashboardCardShell
        title={`${title}加载失败`}
        icon={<AlertCircle className="h-4 w-4" />}
        accent="chart-5"
        className="min-h-[240px]"
        bodyClassName="items-center justify-center gap-3 text-center"
      >
        <AlertCircle className="h-12 w-12 text-chart-negative" />
        <p className="text-sm text-text-muted">
          {query.error instanceof Error ? query.error.message : "未知错误"}
        </p>
        <Button onClick={() => query.refetch()} variant="outline">
          <RefreshCw className="mr-2 h-4 w-4" />
          重试
        </Button>
      </DashboardCardShell>
    );
  }
  if (!query.data) return null;
  if (unavailableReason) {
    return <TabUnavailableState reason={unavailableReason} title={`${title}暂不可用`} />;
  }
  return content(query.data);
}

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

  const overviewQuery = useQuery({
    queryKey: tabQueryKey("topics-overview", novelId, storeTaskId),
    queryFn: () => getTopicsOverviewTab(novelId!, storeTaskId!),
    enabled,
    staleTime: STALE_TIME,
  });

  const seriesQuery = useQuery({
    queryKey: tabQueryKey("topics-series", novelId, storeTaskId),
    queryFn: () => getTopicSeries(novelId!, storeTaskId!),
    enabled,
    staleTime: STALE_TIME,
  });

  const shiftsQuery = useQuery({
    queryKey: tabQueryKey("topics-shifts", novelId, storeTaskId),
    queryFn: () => getTopicShifts(novelId!, storeTaskId!),
    enabled,
    staleTime: STALE_TIME,
  });

  const emotionQuery = useQuery({
    queryKey: tabQueryKey("topics-emotion", novelId, storeTaskId),
    queryFn: () => getTopicEmotion(novelId!, storeTaskId!),
    enabled,
    staleTime: STALE_TIME,
  });

  // 诊断主题标签（topic_labels，按 topic_id 顺序）并入主题词展示
  const topics = useMemo(() => {
    const overview = overviewQuery.data;
    if (!overview) return [];
    const labelMap = new Map<number, string>();
    overview.topics.forEach((topic) => {
      if (topic.label) labelMap.set(topic.topic_id, topic.label!);
    });
    overview.topic_labels?.forEach((label, idx) => {
      if (label && !labelMap.has(idx)) labelMap.set(idx, label);
    });
    return overview.topics.map((topic) => ({
      ...topic,
      label: labelMap.get(topic.topic_id),
    }));
  }, [overviewQuery.data]);

  const overviewUnavailable =
    overviewQuery.data != null &&
    overviewQuery.data.topics.length === 0 &&
    overviewQuery.data.distribution == null
      ? overviewQuery.data.unavailable_reason
      : null;

  return (
    <AnalysisWorkspace title="主题分布">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3 }}
        className="flex min-h-0 flex-1 flex-col"
      >
        <AnalysisWorkspace.Tabs defaultValue="overview">
          <AnalysisWorkspace.Tab value="overview" label="主题总览">
            <motion.div
              className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto pr-1"
              variants={containerVariants}
              initial="hidden"
              animate="visible"
            >
              {renderTabGate(
                overviewQuery,
                "主题总览",
                overviewUnavailable,
                (overview) => (
                  <>
                    {topics.length > 0 && (
                      <>
                        <motion.div variants={itemVariants} className="min-h-[280px]">
                          <TopicWordCloud topics={topics} maxWords={100} className="h-[280px]" />
                        </motion.div>
                        <div className="grid min-h-[300px] grid-cols-1 gap-4 lg:grid-cols-2">
                          <motion.div variants={itemVariants} className="min-h-[300px]">
                            <TopicBarChart topics={topics} className="h-[300px]" />
                          </motion.div>
                          <motion.div variants={itemVariants} className="min-h-[300px]">
                            <TopicTable topics={topics} className="h-[300px]" />
                          </motion.div>
                        </div>
                      </>
                    )}
                    <div className="grid min-h-[320px] grid-cols-1 gap-4 lg:grid-cols-2">
                      <motion.div variants={itemVariants} className="min-h-[320px] rounded-2xl border border-border/60 bg-surface/70 p-4">
                        <TopicDistributionChart
                          distribution={overview.distribution}
                          chapters={overview.chapters}
                          className="h-[300px]"
                        />
                      </motion.div>
                      <motion.div variants={itemVariants} className="min-h-[320px]">
                        <TopicKeywordsCard
                          keywords={overview.keywords}
                          unavailableReason={overview.keyword_unavailable_reason}
                          className="h-[320px]"
                        />
                      </motion.div>
                    </div>
                  </>
                ),
              )}
            </motion.div>
          </AnalysisWorkspace.Tab>

          <AnalysisWorkspace.Tab value="series" label="主题演进">
            {renderTabGate(
              seriesQuery,
              "主题演进",
              seriesQuery.data?.unavailable_reason ?? null,
              (series) => (
                <div className="flex h-full min-h-0 flex-col gap-2">
                  <p className="text-xs text-text-muted">
                    段落级完整 {series.num_topics} 维主题权重堆积图（横轴为真实字符位置，滚轮缩放）；
                    展示层 LTTB 抽稀，不改后端口径。
                  </p>
                  <div className="min-h-[360px] flex-1 rounded-2xl border border-border/60 bg-surface/70 p-3">
                    <TopicSeriesChart
                      points={series.points}
                      numTopics={series.num_topics ?? 0}
                      className="h-[380px]"
                    />
                  </div>
                </div>
              ),
            )}
          </AnalysisWorkspace.Tab>

          <AnalysisWorkspace.Tab value="shifts" label="主题迁移">
            {renderTabGate(
              shiftsQuery,
              "主题迁移",
              shiftsQuery.data?.unavailable_reason ?? null,
              (shifts) => <TopicShiftsPanel candidates={shifts.candidates} config={shifts.config} />,
            )}
          </AnalysisWorkspace.Tab>

          <AnalysisWorkspace.Tab value="emotion" label="主题情绪">
            {renderTabGate(
              emotionQuery,
              "主题情绪",
              emotionQuery.data?.unavailable_reason ?? null,
              (topicEmotion) => <TopicEmotionPanel emotion={topicEmotion.emotion} />,
            )}
          </AnalysisWorkspace.Tab>
        </AnalysisWorkspace.Tabs>
      </motion.div>
    </AnalysisWorkspace>
  );
}
