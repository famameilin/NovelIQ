/**
 * 2026-08-29，作用：展示语言特征分析页面
 * 简要说明：表达结构整合词性、句式、词长和依存统计，词汇与语义整合实体、固定表达和词向量聚合
 */
import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { useParams, useSearchParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { isAnalysisNotCompleteError, getAnalysisNotCompleteRunStatus } from "@/api/errorGuards";
import { getLinguisticFeatures, getLinguisticWord2vec } from "@/api/linguistic";
import { getLinguisticEntitiesTab, tabQueryKey } from "@/api/tabs";
import type { LinguisticEntitiesTabResponse, LinguisticFeaturesResponse, Word2VecStatsResponse } from "@/api/types";
import { useNovelScopedTask, shouldWriteBackTaskUrl } from "@/hooks/useNovelScopedTask";
import { AnalysisNotCompleteState } from "@/components/common/AnalysisNotCompleteState";
import { TabUnavailableState } from "@/components/common/TabUnavailableState";
import { DashboardCardShell } from "@/components/common/DashboardCardShell";
import { AnalysisDetails } from "@/components/common/AnalysisDetails";
import { AnalysisMetricStrip } from "@/components/common/AnalysisMetricStrip";
import { AnalysisViewSwitcher } from "@/components/common/AnalysisViewSwitcher";
import { AnalysisWorkspace } from "@/components/layout/AnalysisWorkspace";
import { RatioBarChart } from "@/components/linguistic/RatioBarChart";
import { PosSimilarityHeatmap } from "@/components/linguistic/PosSimilarityHeatmap";
import { formatAnalysisLabel } from "@/lib/analysisLabels";
import {
  AlignLeft,
  Braces,
  Layers,
  Quote,
  ScanText,
  Sigma,
  Tag,
  Tags,
  BarChart3,
  BookOpen,
} from "lucide-react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const STALE_TIME = 5 * 60 * 1000;

/** 单数据视图的加载、错误和不可用状态门禁 */
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

/**
 * 2026-08-31，作用：将后端不可用原因转换为用户可读文案
 * 简要说明：隐藏内部字段名，保留实际原因中的中文说明
 */
function formatUnavailableReason(reason: string | null | undefined): string | null {
  if (!reason) return null;
  return reason
    .replace(/^\s*linguistic_unavailable\s*:\s*/i, "")
    .replace(/paragraph_linguistic_features/g, "段落语言特征数据")
    .replace(/word2vec/g, "词向量数据");
}

/**
 * 2026-08-31，作用：展示表达结构视图的章节级语言统计
 * 简要说明：统一承载四类比例分布、六项聚合指标和章节切换
 */
function ExpressionStructureView({ query }: { query: UseQueryResultLike<LinguisticFeaturesResponse> }) {
  const [selectedChapter, setSelectedChapter] = useState<string>("book");

  const stats = useMemo(() => {
    const data = query.data;
    if (!data) return null;
    if (selectedChapter === "book") return data;
    return data.chapters.find((chapter) => String(chapter.chapter_id) === selectedChapter) ?? null;
  }, [query.data, selectedChapter]);

  return (
    <motion.div
      className="flex flex-col gap-4"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
    >
      {renderTabGate(query, "表达结构", formatUnavailableReason(query.data?.unavailable_reason), () => (
        <>
          <div className="flex items-center justify-between gap-3">
            <p className="text-xs text-text-muted">
              比例分母为有效词元数或句子数；切换章节查看局部表达结构。
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

          <AnalysisMetricStrip
            items={[
              { label: "全书段落数", value: query.data?.paragraph_count ?? "—" },
              { label: "有效词元数", value: stats?.token_total ?? "—" },
              { label: "句子数", value: stats?.sentence_total ?? "—" },
              { label: "依存根节点数", value: stats?.dependency_root_count ?? "—" },
              { label: "平均依存深度", value: stats?.avg_dependency_depth?.toFixed(3) ?? "—" },
              { label: "最大依存深度", value: stats?.max_dependency_depth ?? "—" },
            ]}
            className="grid-cols-3"
          />

          <div className="grid grid-cols-2 gap-4">
            <RatioBarChart title="词性比例" icon={Tag} ratios={stats?.pos_ratios ?? null} formatLabel={(key) => formatAnalysisLabel(key, "pos")} className="min-h-[280px]" />
            <RatioBarChart title="句式比例" icon={Quote} ratios={stats?.sentence_pattern_ratios ?? null} formatLabel={(key) => formatAnalysisLabel(key, "sentence")} className="min-h-[280px]" />
            <RatioBarChart title="词长分布" icon={AlignLeft} ratios={stats?.word_length_ratios ?? null} formatLabel={(key) => formatAnalysisLabel(key, "wordLength")} className="min-h-[280px]" />
            <RatioBarChart title="依存关系分布" icon={Layers} ratios={stats?.dependency_relation_ratios ?? null} formatLabel={(key) => formatAnalysisLabel(key, "dependency")} className="min-h-[280px]" />
          </div>
        </>
      ))}
    </motion.div>
  );
}

/**
 * 2026-08-31，作用：展示词汇与语义视图的实体、固定表达和词向量聚合
 * 简要说明：不输出向量数组或运行标识，将模型信息收纳到可展开详情
 */
function VocabularySemanticView({
  entitiesQuery,
  word2vecQuery,
}: {
  entitiesQuery: UseQueryResultLike<LinguisticEntitiesTabResponse>;
  word2vecQuery: UseQueryResultLike<Word2VecStatsResponse>;
}) {
  const coverage = word2vecQuery.data?.pos_coverage ?? [];
  const maxCoverage = coverage.length > 0 ? Math.max(...coverage.map((entry) => entry.coverage_ratio ?? 0)) : 0;
  const word2vecData = word2vecQuery.data;

  return (
    <motion.div className="flex flex-col gap-4" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
      {renderTabGate(
        entitiesQuery,
        "词汇与语义",
        formatUnavailableReason(entitiesQuery.data?.unavailable_reason),
        (data) => (
          <div className="flex flex-col gap-4">
            <AnalysisMetricStrip
              items={[
                { label: "固定表达密度（‰）", value: data.fixed_phrase_density?.toFixed(4) ?? "—" },
                { label: "正式命中次数", value: data.metric_hit_count },
                { label: "四字候选数", value: data.four_char_candidate_count },
                { label: "全书字符数", value: data.total_char_count },
                { label: "实体命中总数", value: data.total_hits },
              ]}
              className="grid-cols-5"
            />
            <div className="grid grid-cols-2 gap-4">
              <RatioBarChart
                title="实体类型计数"
                icon={Tags}
                accent="chart-2"
                ratios={data.count_by_type}
                formatValue={(value) => String(Math.round(value))}
                formatLabel={(key) => formatAnalysisLabel(key, "entity")}
                className="min-h-[280px]"
              />
              <DashboardCardShell title="高频实体名（前 20 名）" icon={<ScanText className="h-4 w-4" />} accent="chart-3" className="min-h-[280px]">
                {data.surface_top.length === 0 ? (
                  <p className="py-8 text-center text-sm text-text-muted">暂无实体候选</p>
                ) : (
                  <ul className="space-y-2">
                    {data.surface_top.map((entry) => (
                      <li key={`${entry.entity_type}-${entry.surface_text}`} className="flex items-center gap-3">
                        <span className="w-28 shrink-0 truncate text-sm text-text" title={entry.surface_text}>{entry.surface_text}</span>
                        <span className="rounded bg-primary-subtle px-1.5 py-0.5 text-xs text-primary">
                          {formatAnalysisLabel(entry.entity_type, "entity")}
                        </span>
                        <div className="h-2 min-w-0 flex-1 overflow-hidden rounded-full bg-surface-hover">
                          <div className="h-full rounded-full bg-chart-3" style={{ width: `${data.surface_top[0].count > 0 ? (entry.count / data.surface_top[0].count) * 100 : 0}%` }} />
                        </div>
                        <span className="w-10 shrink-0 text-right text-xs text-text-muted">{entry.count}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </DashboardCardShell>
            </div>
          </div>
        ),
      )}

      {renderTabGate(
        word2vecQuery,
        "词汇与语义",
        formatUnavailableReason(word2vecData?.unavailable_reason),
        (data) => (
          <>
            <div className="grid grid-cols-2 gap-4">
              <DashboardCardShell title="词性覆盖率" icon={<Sigma className="h-4 w-4" />} accent="chart-2" className="min-h-[280px]">
                {coverage.length === 0 ? (
                  <p className="py-8 text-center text-sm text-text-muted">暂无覆盖率数据</p>
                ) : (
                  <ul className="space-y-2">
                    {coverage.map((entry) => (
                      <li key={entry.pos_group} className="flex items-center gap-3">
                        <span className="w-24 shrink-0 truncate text-sm text-text">
                          {formatAnalysisLabel(entry.pos_group, "pos")}
                        </span>
                        <div className="h-2 min-w-0 flex-1 overflow-hidden rounded-full bg-surface-hover">
                          <div className="h-full rounded-full bg-chart-2" style={{ width: `${maxCoverage > 0 && entry.coverage_ratio != null ? (entry.coverage_ratio / maxCoverage) * 100 : 0}%` }} />
                        </div>
                        <span className="w-28 shrink-0 text-right text-xs text-text-muted">
                          {entry.coverage_ratio != null ? `${(entry.coverage_ratio * 100).toFixed(1)}%` : "—"} · {entry.in_vocabulary_token_total}/{entry.source_token_total}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </DashboardCardShell>

              <DashboardCardShell title="词性组语义相似度" icon={<Braces className="h-4 w-4" />} accent="chart-4" className="min-h-[320px]" bodyClassName="min-h-[280px]">
                {data.pos_similarity_matrix && data.pos_centroids.length >= 2 ? (
                  <PosSimilarityHeatmap
                    groups={data.pos_centroids.map((centroid) => formatAnalysisLabel(centroid.pos_group, "pos"))}
                    matrix={data.pos_similarity_matrix}
                    className="h-[280px]"
                  />
                ) : (
                  <p className="flex h-full items-center justify-center text-sm text-text-muted">质心不足 2 组，无法计算相似度矩阵</p>
                )}
              </DashboardCardShell>
            </div>

            <AnalysisDetails title="词汇与语义详情" description="模型信息、覆盖率和质心加权词元统计">
              <div className="grid grid-cols-3 gap-3">
                <div className="rounded-md border border-border/60 bg-surface/70 px-3 py-2"><p className="text-xs text-text-muted">向量维度</p><p className="mt-1 text-sm font-semibold text-text">{data.model?.embedding_dimension ?? "—"}</p></div>
                <div className="rounded-md border border-border/60 bg-surface/70 px-3 py-2"><p className="text-xs text-text-muted">词表规模</p><p className="mt-1 text-sm font-semibold text-text">{data.model?.vocabulary_size ?? "—"}</p></div>
                <div className="rounded-md border border-border/60 bg-surface/70 px-3 py-2"><p className="text-xs text-text-muted">词表来源</p><p className="mt-1 truncate text-sm font-semibold text-text">{formatAnalysisLabel(data.model?.artifact_scope, "artifactScope")}</p></div>
              </div>
              <div className="mt-3 grid grid-cols-3 gap-2">
                {data.pos_centroids.map((centroid) => (
                  <div key={centroid.pos_group} className="flex items-center justify-between rounded-md border border-border/60 bg-surface/70 px-3 py-2 text-xs">
                    <span>{formatAnalysisLabel(centroid.pos_group, "pos")}</span>
                    <span className="text-text-muted">加权词元 {centroid.weighted_token_total}</span>
                  </div>
                ))}
              </div>
            </AnalysisDetails>
          </>
        ),
      )}
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

  const [view, setView] = useState<"structure" | "vocabulary">("structure");

  return (
    <AnalysisWorkspace title="语言特征" documentFlow>
      <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3 }} className="flex flex-col gap-4">
        <AnalysisViewSwitcher
          value={view}
          onValueChange={setView}
          label="语言特征分析视图"
          options={[
            { value: "structure", label: "表达结构", icon: BookOpen },
            { value: "vocabulary", label: "词汇与语义", icon: BarChart3 },
          ]}
        />
        {view === "structure" ? (
          <ExpressionStructureView query={featuresQuery} />
        ) : (
          <VocabularySemanticView entitiesQuery={entitiesQuery} word2vecQuery={word2vecQuery} />
        )}
      </motion.div>
    </AnalysisWorkspace>
  );
}
