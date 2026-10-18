/**
 * TopicsPage - 主题脉络页面
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
import { AnalysisMetricStrip } from "@/components/common/AnalysisMetricStrip";
import { AnalysisViewSwitcher } from "@/components/common/AnalysisViewSwitcher";
import { PagedControls } from "@/components/common/PagedControls";
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

const STALE_TIME = 5 * 60 * 1000;
const OVERVIEW_PAGE_SIZE = 8;
const RANKING_PAGE_SIZE = 10;

type DistributionView = "ranking" | "chapters" | "wordcloud" | "catalog";

function pageItems<T>(items: readonly T[], page: number, pageSize: number) {
  const pageCount = Math.ceil(items.length / pageSize);
  const currentPage = Math.min(page, Math.max(pageCount, 1));
  return {
    page: currentPage,
    pageCount,
    items: items.slice((currentPage - 1) * pageSize, currentPage * pageSize),
  };
}

function balancedPageItems<T>(items: readonly T[], page: number, maxPageSize: number) {
  if (items.length === 0) return { page: 1, pageCount: 0, items: [] as T[] };
  const pageCount = Math.ceil(items.length / maxPageSize);
  const currentPage = Math.min(page, pageCount);
  const baseSize = Math.floor(items.length / pageCount);
  const largerPages = items.length % pageCount;
  const start = (currentPage - 1) * baseSize + Math.min(currentPage - 1, largerPages);
  const size = baseSize + (currentPage <= largerPages ? 1 : 0);
  return { page: currentPage, pageCount, items: items.slice(start, start + size) };
}

/**
 * 展示所选主题的核心分析字段
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
    <DashboardCardShell title={topic ? `主题详情 · ${topic.label || `主题 ${topic.topic_id + 1}`}` : "主题详情"} accent="chart-2" className="min-h-0" bodyClassName="min-h-0 gap-3">
      {topic ? (
        <>
          <AnalysisMetricStrip
            items={[
              { label: "主题占比", value: `${(topic.weight * 100).toFixed(1)}%` },
              { label: "净情绪", value: emotion?.emotion != null ? emotion.emotion.toFixed(4) : "—" },
              { label: "加权文本量", value: emotion?.weighted_token_total != null ? Math.round(emotion.weighted_token_total).toLocaleString() : "—" },
              { label: "占比最高章节", value: topChapter ? `第 ${topChapter.chapter_sequence} 章` : "—" },
            ]}
            className="grid-cols-4 [&>div]:px-2.5 [&>div]:py-1.5 [&>div>dd]:text-base"
          />
          <div className="rounded-xl border border-border/60 bg-surface/70 p-3">
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

  // 小说作用域任务守卫——跨小说切换后旧小说的任务
  // 不得用于新小说的查询，也不得回写固化成新小说 URL（模式同 GraphPage）
  const { storeTaskId, urlTaskSyncRef } = useNovelScopedTask(novelId, urlTaskId);

  useEffect(() => {
    if (!novelId || !storeTaskId) return;
    if (!shouldWriteBackTaskUrl(urlTaskId, storeTaskId, urlTaskSyncRef)) return;
    navigate(`/novels/${novelId}/topics?task_id=${storeTaskId}`, { replace: true });
  }, [navigate, novelId, storeTaskId, urlTaskId, urlTaskSyncRef]);

  const enabled = !!novelId && !!storeTaskId;
  const [activeTab, setActiveTab] = useState("overview");

  const overviewQuery = useQuery({
    queryKey: tabQueryKey("topics-overview", novelId, storeTaskId),
    queryFn: () => getTopicsOverviewTab(novelId!, storeTaskId!),
    enabled,
    staleTime: STALE_TIME,
  });

  const seriesQuery = useQuery({
    queryKey: tabQueryKey("topics-series", novelId, storeTaskId),
    queryFn: () => getTopicSeries(novelId!, storeTaskId!),
    enabled: enabled && activeTab === "series",
    staleTime: STALE_TIME,
  });

  const shiftsQuery = useQuery({
    queryKey: tabQueryKey("topics-shifts", novelId, storeTaskId),
    queryFn: () => getTopicShifts(novelId!, storeTaskId!),
    enabled: enabled && activeTab === "shifts",
    staleTime: STALE_TIME,
  });

  const emotionQuery = useQuery({
    queryKey: tabQueryKey("topics-emotion", novelId, storeTaskId),
    queryFn: () => getTopicEmotion(novelId!, storeTaskId!),
    enabled,
    staleTime: STALE_TIME,
  });

  // 诊断标签只能按 topic_id 绑定；历史无 ID 数组不得猜测对应关系。
  const topics = useMemo(() => {
    const overview = overviewQuery.data;
    if (!overview) return [];
    const labelMap = new Map<number, string>();
    overview.topics.forEach((topic) => {
      if (topic.label) labelMap.set(topic.topic_id, topic.label!);
    });
    Object.entries(overview.topic_labels ?? {}).forEach(([topicId, label]) => {
      const id = Number(topicId);
      if (Number.isInteger(id) && label && !labelMap.has(id)) labelMap.set(id, label);
    });
    return overview.topics
      .map((topic) => ({
        ...topic,
        label: labelMap.get(topic.topic_id),
      }))
      .sort((left, right) => right.weight - left.weight);
  }, [overviewQuery.data]);
  const topicLabels = useMemo(
    () => Object.fromEntries(topics.filter((topic) => topic.label).map((topic) => [topic.topic_id, topic.label!])),
    [topics],
  );

  const overviewUnavailable =
    overviewQuery.data != null &&
    overviewQuery.data.topics.length === 0 &&
    overviewQuery.data.distribution == null
      ? overviewQuery.data.unavailable_reason
      : null;

  const [selectedTopicId, setSelectedTopicId] = useState<number | null>(null);
  const [overviewPage, setOverviewPage] = useState(1);
  const [rankingPage, setRankingPage] = useState(1);
  const [distributionView, setDistributionView] = useState<DistributionView>("ranking");
  const activeSelectedTopicId = topics.some((topic) => topic.topic_id === selectedTopicId)
    ? selectedTopicId
    : topics[0]?.topic_id ?? null;
  const selectedTopic = topics.find((topic) => topic.topic_id === activeSelectedTopicId) ?? null;
  const selectedEmotion = emotionQuery.data?.emotion.find((entry) => entry.topic_id === activeSelectedTopicId);
  const overviewTopics = balancedPageItems(topics, overviewPage, OVERVIEW_PAGE_SIZE);
  const rankedTopics = pageItems(topics, rankingPage, RANKING_PAGE_SIZE);
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
        <AnalysisWorkspace.Tabs value={activeTab} onValueChange={setActiveTab}>
          <AnalysisWorkspace.Tab value="overview" label="主题总览">
            <div className="h-full min-h-0">
              {renderTabGate(overviewQuery, "主题总览", overviewUnavailable, (overview) => (
                <div className="grid h-full min-h-0 grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)] gap-4">
                  <DashboardCardShell title={`主题列表 · ${topics.length} 个`} accent="chart-1" className="h-full min-h-0" contentClassName="flex h-full flex-col" bodyClassName="min-h-0 flex-1 gap-3">
                    <div className="grid min-h-0 flex-1 auto-rows-fr gap-2" aria-label="主题列表">
                      {overviewTopics.items.length > 0 ? overviewTopics.items.map((topic) => (
                        <button key={topic.topic_id} type="button" onClick={() => setSelectedTopicId(topic.topic_id)} aria-pressed={activeSelectedTopicId === topic.topic_id} className={`flex min-h-0 items-center justify-between gap-3 rounded-lg border px-3 text-left transition-colors ${activeSelectedTopicId === topic.topic_id ? "border-primary/40 bg-primary/10" : "border-border/60 hover:bg-surface-hover"}`}>
                          <span className="min-w-0 truncate text-sm font-medium text-text" title={topic.label || `主题 ${topic.topic_id + 1}`}>{topic.label || `主题 ${topic.topic_id + 1}`}</span>
                          <span className="shrink-0 text-xs tabular-nums text-text-muted">{(topic.weight * 100).toFixed(1)}%</span>
                        </button>
                      )) : <p className="text-sm text-text-muted">暂无主题数据</p>}
                    </div>
                    <PagedControls page={overviewTopics.page} pageCount={overviewTopics.pageCount} onPageChange={(page) => {
                      setOverviewPage(page);
                      setSelectedTopicId(balancedPageItems(topics, page, OVERVIEW_PAGE_SIZE).items[0]?.topic_id ?? null);
                    }} label="主题列表" />
                  </DashboardCardShell>
                  <div className="grid min-h-0 grid-rows-[auto_minmax(0,1fr)] gap-4">
                    <TopicDetailPanel topic={selectedTopic} emotion={selectedEmotion} topChapter={topChapter} />
                    <TopicKeywordsCard keywords={overview.keywords} unavailableReason={overview.keyword_unavailable_reason} columns={2} className="h-full min-h-0" />
                  </div>
                </div>
              ))}
            </div>
          </AnalysisWorkspace.Tab>

          <AnalysisWorkspace.Tab value="distribution" label="完整主题分布">
            <div className="h-full min-h-0">
              {renderTabGate(overviewQuery, "完整主题分布", overviewUnavailable, (overview) => (
                <div className="flex h-full min-h-0 flex-col gap-3">
                  <div className="flex shrink-0 items-center justify-between gap-3">
                    <p className="text-xs text-text-muted">{topics.length} 个主题 · {overview.chapters.length} 个章节，选择视图查看完整数据</p>
                    <AnalysisViewSwitcher value={distributionView} onValueChange={setDistributionView} label="主题分布视图" options={[
                      { value: "ranking", label: "权重排行" },
                      { value: "chapters", label: "全书与章节" },
                      { value: "wordcloud", label: "关键词词云" },
                      { value: "catalog", label: "主题清单" },
                    ]} />
                  </div>
                  <div className="min-h-0 flex-1">
                    {distributionView === "ranking" && <div className="flex h-full min-h-0 flex-col gap-2">
                      <TopicBarChart topics={rankedTopics.items} className="min-h-0 flex-1" />
                      <PagedControls page={rankedTopics.page} pageCount={rankedTopics.pageCount} onPageChange={setRankingPage} label="主题权重" />
                    </div>}
                    {distributionView === "chapters" && <div className="h-full min-h-0 rounded-xl border border-border/60 bg-surface/70 p-4">
                      <TopicDistributionChart distribution={overview.distribution} chapters={overview.chapters} className="h-full" />
                    </div>}
                    {distributionView === "wordcloud" && <TopicWordCloud topics={topics} maxWords={100} className="h-full min-h-0" />}
                    {distributionView === "catalog" && <div className="grid h-full min-h-0 grid-cols-[minmax(0,1.15fr)_minmax(0,0.85fr)] gap-4">
                      <TopicTable topics={topics} className="h-full min-h-0" />
                      <TopicKeywordsCard keywords={overview.keywords} unavailableReason={overview.keyword_unavailable_reason} columns={2} className="h-full min-h-0" />
                    </div>}
                  </div>
                </div>
              ))}
            </div>
          </AnalysisWorkspace.Tab>

          <AnalysisWorkspace.Tab value="series" label="主题演进">
            <div className="h-full min-h-0">
              {renderTabGate(seriesQuery, "主题演进", seriesQuery.data?.unavailable_reason ?? null, (series) => (
                <DashboardCardShell title="主题演进" accent="chart-2" className="h-full" contentClassName="flex h-full flex-col" bodyClassName="min-h-0 flex-1 gap-2">
                  <p className="text-xs text-text-muted">按等长字符区间汇总 {series.num_topics} 个主题的段落权重，入模词元加权；色阶在 95 分位封顶，悬停查看精确值。</p>
                  <TopicSeriesChart points={series.points} numTopics={series.num_topics ?? 0} topicLabels={topicLabels} className="min-h-[320px] flex-1" />
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
                <TopicEmotionPanel emotion={topicEmotion.emotion} topicLabels={topicLabels} />
              ))}
            </div>
          </AnalysisWorkspace.Tab>
        </AnalysisWorkspace.Tabs>
      </motion.div>
    </AnalysisWorkspace>
  );
}
