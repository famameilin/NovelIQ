/**
 * LinguisticPage - 语言特征页面（2026-08-29 新增，赛道 A/B/C 数据落地）
 *
 * 三个 tab，每 tab 一个 API：
 * - 词法句法   → GET /linguistic/features（词性/句式/词长/依存聚合，book + chapters）
 * - 实体与短语 → GET /tabs/linguistic-entities（实体类型计数 + 高频实体 + 短语统计，仅聚合）
 * - 词向量     → GET /linguistic/word2vec（POS 覆盖率 + 质心相似度矩阵）
 */
import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { useParams, useSearchParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { isAnalysisNotCompleteError, getAnalysisNotCompleteRunStatus } from "@/api/errorGuards";
import { getLinguisticFeatures, getLinguisticWord2vec } from "@/api/linguistic";
import { getLinguisticEntitiesTab, tabQueryKey } from "@/api/tabs";
import type { LinguisticFeaturesResponse } from "@/api/types";
import { useNovelScopedTask, shouldWriteBackTaskUrl } from "@/hooks/useNovelScopedTask";
import { AnalysisNotCompleteState } from "@/components/common/AnalysisNotCompleteState";
import { TabUnavailableState } from "@/components/common/TabUnavailableState";
import { DashboardCardShell } from "@/components/common/DashboardCardShell";
import { AnalysisWorkspace } from "@/components/layout/AnalysisWorkspace";
import { RatioBarChart } from "@/components/linguistic/RatioBarChart";
import { PosSimilarityHeatmap } from "@/components/linguistic/PosSimilarityHeatmap";
import {
  AlignLeft,
  Braces,
  Layers,
  Quote,
  ScanText,
  Sigma,
  Tag,
  Tags,
} from "lucide-react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const STALE_TIME = 5 * 60 * 1000;

/** 单 tab 的加载/错误态统一门禁（与 TopicsPage 同款语义） */
function renderTabGate<T>(
  query: UseQueryResultLike<T>,
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
        title={failed ? "语言特征任务已失败" : "语言特征结果尚未完成"}
        description={
          failed
            ? "该分析任务已失败，语言特征结果无法读取，请重新发起分析后再查看。"
            : "当前任务仍在分析中，语言特征结果暂时不可读，请等待任务进入完成态后再查看。"
        }
        failed={failed}
      />
    );
  }
  if (query.isError) {
    return <TabUnavailableState reason={String(query.error ?? "加载失败")} title={`${title}加载失败`} />;
  }
  if (!query.data) return null;
  if (unavailableReason) {
    return <TabUnavailableState reason={unavailableReason} title={`${title}暂不可用`} />;
  }
  return content(query.data);
}

/** renderTabGate 所需的最小查询形状（避免泛型 UseQueryResult 的判别联合展开） */
interface UseQueryResultLike<T> {
  isLoading: boolean;
  isError: boolean;
  error: unknown;
  data: T | undefined;
  refetch: () => unknown;
}

function LexiconTab({ query }: { query: UseQueryResultLike<LinguisticFeaturesResponse> }) {
  const [selectedChapter, setSelectedChapter] = useState<string>("book");

  const stats = useMemo(() => {
    const data = query.data;
    if (!data) return null;
    if (selectedChapter === "book") return data;
    return data.chapters.find((chapter) => String(chapter.chapter_id) === selectedChapter) ?? null;
  }, [query.data, selectedChapter]);

  return (
    <motion.div
      className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto pr-1"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
    >
      {renderTabGate(query, "词法句法", query.data?.unavailable_reason ?? null, () => (
        <>
          <div className="flex items-center justify-between">
            <p className="text-xs text-text-muted">
              比例分母为有效 LTP 词元数或句子数；切换章节查看局部风格。
            </p>
            <Select value={selectedChapter} onValueChange={setSelectedChapter}>
              <SelectTrigger className="h-8 w-[160px]" aria-label="聚合层级">
                <SelectValue placeholder="聚合层级" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="book">全书</SelectItem>
                {query.data?.chapters.map((chapter) => (
                  <SelectItem key={chapter.chapter_id} value={String(chapter.chapter_id)}>
                    第 {chapter.chapter_id} 章
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <RatioBarChart title="词性比例" icon={Tag} ratios={stats?.pos_ratios ?? null} className="min-h-[280px]" />
            <RatioBarChart title="句式比例" icon={Quote} ratios={stats?.sentence_pattern_ratios ?? null} className="min-h-[280px]" />
            <RatioBarChart title="词长分布" icon={AlignLeft} ratios={stats?.word_length_ratios ?? null} className="min-h-[280px]" />
            <RatioBarChart title="依存关系分布" icon={Layers} ratios={stats?.dependency_relation_ratios ?? null} className="min-h-[280px]" />
          </div>

          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            <DashboardCardShell title="平均依存深度" accent="primary" className="min-h-[120px]" bodyClassName="items-center justify-center">
              <p className="text-2xl font-semibold text-text">{stats?.avg_dependency_depth?.toFixed(3) ?? "—"}</p>
            </DashboardCardShell>
            <DashboardCardShell title="最大依存深度" accent="chart-2" className="min-h-[120px]" bodyClassName="items-center justify-center">
              <p className="text-2xl font-semibold text-text">{stats?.max_dependency_depth ?? "—"}</p>
            </DashboardCardShell>
            <DashboardCardShell title="有效词元数" accent="chart-3" className="min-h-[120px]" bodyClassName="items-center justify-center">
              <p className="text-2xl font-semibold text-text">{stats?.token_total ?? "—"}</p>
            </DashboardCardShell>
            <DashboardCardShell title="句子数" accent="chart-4" className="min-h-[120px]" bodyClassName="items-center justify-center">
              <p className="text-2xl font-semibold text-text">{stats?.sentence_total ?? "—"}</p>
            </DashboardCardShell>
          </div>
        </>
      ))}
    </motion.div>
  );
}

export function LinguisticPage() {
  const { novelId } = useParams<{ novelId: string }>();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();

  const urlTaskId = searchParams.get("task_id");
  const { storeTaskId, urlTaskSyncRef } = useNovelScopedTask(novelId, urlTaskId);

  useEffect(() => {
    if (!novelId || !storeTaskId) return;
    if (!shouldWriteBackTaskUrl(urlTaskId, storeTaskId, urlTaskSyncRef)) return;
    navigate(`/novels/${novelId}/linguistic?task_id=${storeTaskId}`, { replace: true });
  }, [navigate, novelId, storeTaskId, urlTaskId, urlTaskSyncRef]);

  const enabled = !!novelId && !!storeTaskId;

  const featuresQuery = useQuery({
    queryKey: tabQueryKey("linguistic-lexicon", novelId, storeTaskId),
    queryFn: () => getLinguisticFeatures(novelId!, storeTaskId!),
    enabled,
    staleTime: STALE_TIME,
  });

  const entitiesQuery = useQuery({
    queryKey: tabQueryKey("linguistic-entities", novelId, storeTaskId),
    queryFn: () => getLinguisticEntitiesTab(novelId!, storeTaskId!),
    enabled,
    staleTime: STALE_TIME,
  });

  const word2vecQuery = useQuery({
    queryKey: tabQueryKey("linguistic-word2vec", novelId, storeTaskId),
    queryFn: () => getLinguisticWord2vec(novelId!, storeTaskId!),
    enabled,
    staleTime: STALE_TIME,
  });

  const coverage = word2vecQuery.data?.pos_coverage ?? [];
  const maxCoverage = coverage.length > 0 ? Math.max(...coverage.map((entry) => entry.coverage_ratio ?? 0)) : 0;

  return (
    <AnalysisWorkspace title="语言特征">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3 }}
        className="flex min-h-0 flex-1 flex-col"
      >
        <AnalysisWorkspace.Tabs defaultValue="lexicon">
          <AnalysisWorkspace.Tab value="lexicon" label="词法句法">
            <LexiconTab query={featuresQuery} />
          </AnalysisWorkspace.Tab>

          <AnalysisWorkspace.Tab value="entities" label="实体与短语">
            {renderTabGate(
              entitiesQuery,
              "实体与短语",
              entitiesQuery.data != null &&
                entitiesQuery.data.count_by_type && Object.keys(entitiesQuery.data.count_by_type).length === 0 &&
                entitiesQuery.data.total_hits === 0
                ? entitiesQuery.data.unavailable_reason
                : null,
              (data) => (
                <motion.div
                  className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto pr-1"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                >
                  <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
                    <DashboardCardShell title="固定短语密度(‰)" accent="primary" className="min-h-[120px]" bodyClassName="items-center justify-center">
                      <p className="text-2xl font-semibold text-text">{data.fixed_phrase_density?.toFixed(4) ?? "—"}</p>
                    </DashboardCardShell>
                    <DashboardCardShell title="正式命中次数" accent="chart-2" className="min-h-[120px]" bodyClassName="items-center justify-center">
                      <p className="text-2xl font-semibold text-text">{data.metric_hit_count}</p>
                    </DashboardCardShell>
                    <DashboardCardShell title="四字候选" accent="chart-3" className="min-h-[120px]" bodyClassName="items-center justify-center">
                      <p className="text-2xl font-semibold text-text">{data.four_char_candidate_count}</p>
                    </DashboardCardShell>
                    <DashboardCardShell title="全书字符数" accent="chart-4" className="min-h-[120px]" bodyClassName="items-center justify-center">
                      <p className="text-2xl font-semibold text-text">{data.total_char_count}</p>
                    </DashboardCardShell>
                  </div>

                  <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                    <RatioBarChart
                      title="实体类型计数"
                      icon={Tags}
                      accent="chart-2"
                      ratios={data.count_by_type}
                      formatValue={(value) => String(Math.round(value))}
                      className="min-h-[280px]"
                    />
                    <DashboardCardShell title="高频实体名 Top-20" icon={<ScanText className="h-4 w-4" />} accent="chart-3" className="min-h-[280px]" bodyClassName="min-h-0 overflow-y-auto">
                      {data.surface_top.length === 0 ? (
                        <p className="py-8 text-center text-sm text-text-muted">暂无实体候选</p>
                      ) : (
                        <ul className="space-y-2">
                          {data.surface_top.map((entry) => (
                            <li key={`${entry.entity_type}-${entry.surface_text}`} className="flex items-center gap-3">
                              <span className="w-28 shrink-0 truncate text-sm text-text">{entry.surface_text}</span>
                              <span className="rounded bg-primary-subtle px-1.5 py-0.5 text-xs text-primary">{entry.entity_type}</span>
                              <div className="h-2 min-w-0 flex-1 overflow-hidden rounded-full bg-surface-hover">
                                <div
                                  className="h-full rounded-full bg-chart-3"
                                  style={{
                                    width: `${
                                      data.surface_top[0].count > 0 ? (entry.count / data.surface_top[0].count) * 100 : 0
                                    }%`,
                                  }}
                                />
                              </div>
                              <span className="w-10 shrink-0 text-right text-xs text-text-muted">{entry.count}</span>
                            </li>
                          ))}
                        </ul>
                      )}
                    </DashboardCardShell>
                  </div>
                </motion.div>
              ),
            )}
          </AnalysisWorkspace.Tab>

          <AnalysisWorkspace.Tab value="word2vec" label="词向量">
            {renderTabGate(
              word2vecQuery,
              "词向量",
              word2vecQuery.data?.unavailable_reason ?? null,
              (data) => (
                <motion.div
                  className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto pr-1"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                >
                  <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
                    <DashboardCardShell title="向量维度" accent="primary" className="min-h-[110px]" bodyClassName="items-center justify-center">
                      <p className="text-2xl font-semibold text-text">{data.model?.embedding_dimension ?? "—"}</p>
                    </DashboardCardShell>
                    <DashboardCardShell title="词表规模" accent="chart-2" className="min-h-[110px]" bodyClassName="items-center justify-center">
                      <p className="text-2xl font-semibold text-text">{data.model?.vocabulary_size ?? "—"}</p>
                    </DashboardCardShell>
                    <DashboardCardShell title="词表来源" accent="chart-3" className="min-h-[110px]" bodyClassName="items-center justify-center">
                      <p className="truncate text-lg font-semibold text-text">{data.model?.artifact_scope ?? "—"}</p>
                    </DashboardCardShell>
                  </div>

                  <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                    <DashboardCardShell title="词性覆盖率" icon={<Sigma className="h-4 w-4" />} accent="chart-2" className="min-h-[280px]" bodyClassName="min-h-0 overflow-y-auto">
                      {coverage.length === 0 ? (
                        <p className="py-8 text-center text-sm text-text-muted">暂无覆盖率数据</p>
                      ) : (
                        <ul className="space-y-2">
                          {coverage.map((entry) => (
                            <li key={entry.pos_group} className="flex items-center gap-3">
                              <span className="w-24 shrink-0 truncate text-sm text-text">{entry.pos_group}</span>
                              <div className="h-2 min-w-0 flex-1 overflow-hidden rounded-full bg-surface-hover">
                                <div
                                  className="h-full rounded-full bg-chart-2"
                                  style={{
                                    width: `${maxCoverage > 0 && entry.coverage_ratio != null ? (entry.coverage_ratio / maxCoverage) * 100 : 0}%`,
                                  }}
                                />
                              </div>
                              <span className="w-32 shrink-0 text-right text-xs text-text-muted">
                                {entry.in_vocabulary_token_total} / {entry.source_token_total}
                              </span>
                            </li>
                          ))}
                        </ul>
                      )}
                    </DashboardCardShell>

                    <DashboardCardShell title="词性组语义相似度" icon={<Braces className="h-4 w-4" />} accent="chart-4" className="min-h-[320px]" bodyClassName="min-h-[280px]">
                      {data.pos_similarity_matrix && data.pos_centroids.length >= 2 ? (
                        <PosSimilarityHeatmap
                          groups={data.pos_centroids.map((centroid) => centroid.pos_group)}
                          matrix={data.pos_similarity_matrix}
                          className="h-[280px]"
                        />
                      ) : (
                        <p className="flex h-full items-center justify-center text-sm text-text-muted">
                          质心不足 2 组，无法计算相似度矩阵
                        </p>
                      )}
                    </DashboardCardShell>
                  </div>
                </motion.div>
              ),
            )}
          </AnalysisWorkspace.Tab>
        </AnalysisWorkspace.Tabs>
      </motion.div>
    </AnalysisWorkspace>
  );
}
