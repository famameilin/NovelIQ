/**
 * TopicsPage - 主题脉络页面（2026-08-31 固定工作区）
 *
 * 以业务页签保留主题总览、完整分布、主题演进、主题迁移和主题情绪五类指标
 */
import { useEffect, useMemo, useState } from "react";
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
import { AnalysisDetails } from "@/components/common/AnalysisDetails";
import { AnalysisMetricStrip } from "@/components/common/AnalysisMetricStrip";
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
import type { ChapterTopicDistribution, Topic, TopicEmotionEntry } from "@/api/types";
import { formatAnalysisLabel } from "@/lib/analysisLabels";

const STALE_TIME = 5 * 60 * 1000;

/**
 * 2026-08-31，作用：展示所选主题的核心分析字段
 * 简要说明：将占比、代表词、净情绪、加权文本量和最高章节放在同一信息面
 */
function TopicDetailPanel({
  topic,
  emotion,
  topChapter,
}: {
  topic: Topic | null;
  emotion: TopicEmotionEntry | undefined;
  topChapter: ChapterTopicDistribution | undefined;
}) {
  return (
    <DashboardCardShell title={topic ? `主题详情 · ${topic.label || `主题 ${topic.topic_id + 1}`}` : "主题详情"} accent="chart-2" className="h-full" bodyClassName="gap-4">
      {topic ? (
        <>
          <AnalysisMetricStrip
            items={[
              { label: "主题占比", value: `${(topic.weight * 100).toFixed(1)}%` },
              { label: "净情绪", value: emotion?.emotion != null ? emotion.emotion.toFixed(4) : "—" },
              { label: "加权文本量", value: emotion?.weighted_token_total != null ? Math.round(emotion.weighted_token_total).toLocaleString() : "—" },
              { label: "占比最高章节", value: topChapter ? `第 ${topChapter.chapter_sequence} 章` : "—", description: topChapter ? `${((topChapter.distribution?.find((entry) => entry.topic_id === topic.topic_id)?.weight ?? 0) * 100).toFixed(1)}%` : "暂无章节分布" },
            ]}
            className="grid-cols-4"
          />
          <div className="rounded-xl border border-border/60 bg-surface/70 p-4">
            <p className="text-xs font-medium text-text-muted">代表词</p>
            <div className="mt-2 flex flex-wrap gap-2">
              {topic.words.length > 0 ? topic.words.map((word) => <span key={word} className="rounded-md bg-primary/10 px-2 py-1 text-xs text-primary">{word}</span>) : <span className="text-sm text-text-muted">暂无代表词</span>}
            </div>
          </div>
        </>
      ) : (
        <p className="text-sm text-text-muted">选择主题后查看详细指标。</p>
      )}
    </DashboardCardShell>
  );
}

/** 单数据视图的加载、错误和不可用状态门禁 */
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
    return overview.topics
      .map((topic) => ({
        ...topic,
        label: labelMap.get(topic.topic_id),
      }))
      .sort((left, right) => right.weight - left.weight);
  }, [overviewQuery.data]);

  const overviewUnavailable =
    overviewQuery.data != null &&
    overviewQuery.data.topics.length === 0 &&
    overviewQuery.data.distribution == null
      ? overviewQuery.data.unavailable_reason
      : null;

  const [selectedTopicId, setSelectedTopicId] = useState<number | null>(null);
  const activeSelectedTopicId = topics.some((topic) => topic.topic_id === selectedTopicId)
    ? selectedTopicId
    : topics[0]?.topic_id ?? null;
  const selectedTopic = topics.find((topic) => topic.topic_id === activeSelectedTopicId) ?? null;
  const selectedEmotion = emotionQuery.data?.emotion.find((entry) => entry.topic_id === activeSelectedTopicId);
  const primaryTopics = topics.slice(0, 8);
  const topChapter = useMemo(() => {
    if (!selectedTopic || !overviewQuery.data) return undefined;
    return overviewQuery.data.chapters
      .filter((chapter) => chapter.distribution != null)
      .reduce<ChapterTopicDistribution | undefined>((top, chapter) => {
        const weight = chapter.distribution?.find((entry) => entry.topic_id === selectedTopic.topic_id)?.weight ?? 0;
        const topWeight = top?.distribution?.find((entry) => entry.topic_id === selectedTopic.topic_id)?.weight ?? -1;
        return weight > topWeight ? chapter : top;
      }, undefined);
  }, [overviewQuery.data, selectedTopic]);

  return (
    <AnalysisWorkspace title="主题脉络">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3 }}
        className="flex h-full min-h-0 flex-col"
      >
        <AnalysisWorkspace.Tabs defaultValue="overview">
          <AnalysisWorkspace.Tab value="overview" label="主题总览">
            <div className="flex h-full min-h-0 flex-col overflow-y-auto pr-2">
              {renderTabGate(overviewQuery, "主题总览", overviewUnavailable, () => (
                <div className="flex flex-col gap-4">
            <section className="grid grid-cols-[minmax(240px,0.8fr)_minmax(0,1.2fr)] gap-4">
              <DashboardCardShell title="主题列表" accent="chart-1" bodyClassName="gap-2">
                {primaryTopics.length > 0 ? primaryTopics.map((topic) => (
                  <button key={topic.topic_id} type="button" onClick={() => setSelectedTopicId(topic.topic_id)} aria-pressed={activeSelectedTopicId === topic.topic_id} className={`flex items-center justify-between gap-3 rounded-lg border px-3 py-2 text-left transition-colors ${activeSelectedTopicId === topic.topic_id ? "border-primary/40 bg-primary/10" : "border-border/60 hover:bg-surface-hover"}`}>
                    <span className="min-w-0 truncate text-sm font-medium text-text">{topic.label || `主题 ${topic.topic_id + 1}`}</span>
                    <span className="shrink-0 text-xs tabular-nums text-text-muted">{(topic.weight * 100).toFixed(1)}%</span>
                  </button>
                )) : <p className="text-sm text-text-muted">暂无主题数据</p>}
                {topics.length > primaryTopics.length ? (
                  <p className="pt-1 text-xs text-text-muted">其余 {topics.length - primaryTopics.length} 个主题收纳在完整主题分布中</p>
                ) : null}
              </DashboardCardShell>
              <TopicDetailPanel topic={selectedTopic} emotion={selectedEmotion} topChapter={topChapter} />
            </section>
            <AnalysisDetails title="分析详情" description="模型元数据与主题迁移配置">
              <div className="grid grid-cols-2 gap-4">
                <div className="grid grid-cols-2 gap-3 text-sm">
                  <span className="text-text-muted">主题模型</span><span className="text-text">{formatAnalysisLabel(overviewQuery.data?.model?.model_key, "topicModel")}</span>
                  <span className="text-text-muted">库版本</span><span className="text-text">{overviewQuery.data?.model?.library_version ?? "—"}</span>
                  <span className="text-text-muted">流水线版本</span><span className="text-text">{overviewQuery.data?.model?.pipeline_version ?? "—"}</span>
                  <span className="text-text-muted">主题数量</span><span className="text-text">{overviewQuery.data?.model?.num_topics ?? "—"}</span>
                </div>
                <div className="grid grid-cols-2 gap-3 text-sm">
                  <span className="text-text-muted">窗口段数</span><span className="text-text">{shiftsQuery.data?.config.window_size ?? "—"}</span>
                  <span className="text-text-muted">每窗最少词元</span><span className="text-text">{shiftsQuery.data?.config.min_tokens_per_window ?? "—"}</span>
                  <span className="text-text-muted">散度阈值</span><span className="text-text">{shiftsQuery.data?.config.score_threshold ?? "—"}</span>
                  <span className="text-text-muted">候选上限</span><span className="text-text">{shiftsQuery.data?.config.max_candidates ?? "—"}</span>
                </div>
              </div>
            </AnalysisDetails>
                </div>
              ))}
            </div>
          </AnalysisWorkspace.Tab>

          <AnalysisWorkspace.Tab value="distribution" label="完整主题分布">
            <div className="h-full min-h-0 overflow-y-auto pr-2">
              {renderTabGate(overviewQuery, "完整主题分布", overviewUnavailable, (overview) => (
                <div className="space-y-4">
                  {topics.length > 0 ? (
                    <>
                      <TopicWordCloud topics={topics} maxWords={100} className="h-[300px]" />
                      <TopicBarChart topics={topics} className="h-[360px]" />
                      <TopicTable topics={topics} />
                    </>
                  ) : null}
                  <div className="grid grid-cols-2 gap-4">
                    <div className="min-h-[280px] rounded-lg border border-border/60 bg-surface/70 p-4">
                      <TopicDistributionChart distribution={overview.distribution} chapters={overview.chapters} className="h-[260px]" />
                    </div>
                    <TopicKeywordsCard keywords={overview.keywords} unavailableReason={overview.keyword_unavailable_reason} className="min-h-[280px]" />
                  </div>
                </div>
              ))}
            </div>
          </AnalysisWorkspace.Tab>

          <AnalysisWorkspace.Tab value="series" label="主题演进">
            <div className="h-full min-h-0">
              {renderTabGate(seriesQuery, "主题演进", seriesQuery.data?.unavailable_reason ?? null, (series) => (
                <DashboardCardShell title="主题演进" accent="chart-2" className="h-full" contentClassName="flex h-full flex-col" bodyClassName="min-h-0 flex-1 gap-2">
                  <p className="text-xs text-text-muted">段落级完整 {series.num_topics} 维主题权重堆积图，横轴为真实字符位置。</p>
                  <TopicSeriesChart points={series.points} numTopics={series.num_topics ?? 0} className="min-h-[320px] flex-1" />
                </DashboardCardShell>
              ))}
            </div>
          </AnalysisWorkspace.Tab>

          <AnalysisWorkspace.Tab value="shifts" label="主题迁移">
            <div className="h-full min-h-0">
              {renderTabGate(shiftsQuery, "主题迁移", shiftsQuery.data?.unavailable_reason ?? null, (shifts) => (
                <TopicShiftsPanel candidates={shifts.candidates} config={shifts.config} showConfig className="h-full" />
              ))}
            </div>
          </AnalysisWorkspace.Tab>

          <AnalysisWorkspace.Tab value="emotion" label="主题情绪">
            <div className="h-full min-h-0">
              {renderTabGate(emotionQuery, "主题情绪", emotionQuery.data?.unavailable_reason ?? null, (topicEmotion) => (
                <TopicEmotionPanel emotion={topicEmotion.emotion} />
              ))}
            </div>
          </AnalysisWorkspace.Tab>
        </AnalysisWorkspace.Tabs>
      </motion.div>
    </AnalysisWorkspace>
  );
}
