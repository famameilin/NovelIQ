import { useMemo, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { isAnalysisNotCompleteError, getAnalysisNotCompleteRunStatus } from "@/api/errorGuards";
import { getDiagnosis, getForeshadowingThreads } from "@/api/results";
import { useNovelScopedTask } from "@/hooks/useNovelScopedTask";
import { AnalysisNotCompleteState } from "@/components/common/AnalysisNotCompleteState";
import { AnalysisDetails } from "@/components/common/AnalysisDetails";
import { AnalysisMetricStrip } from "@/components/common/AnalysisMetricStrip";
import { AnalysisViewSwitcher } from "@/components/common/AnalysisViewSwitcher";
import { AnalysisWorkspace } from "@/components/layout/AnalysisWorkspace";
import { DashboardCardShell } from "@/components/common/DashboardCardShell";
import { ScoreCard } from "@/components/common/ScoreCard";
import { DiagnosisHeader } from "@/components/diagnosis/DiagnosisHeader";
import { DiagnosisText } from "@/components/diagnosis/DiagnosisText";
import { ValueLogicCard } from "@/components/diagnosis/ValueLogicCard";
import { TopicLabels } from "@/components/diagnosis/TopicLabels";
import { CharacterCastCard } from "@/components/diagnosis/CharacterCastCard";
import { ArcScoresChart } from "@/components/charts/ArcScoresChart";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { AlertCircle, FileText, GitBranch, Tags } from "lucide-react";
import type { ForeshadowingThread } from "@/api/types";
import { cn } from "@/lib/cn";

const STALE_TIME = 5 * 60 * 1000;

/** 统一 diagnosis thread 状态到标签文案 */
function getThreadStatusMeta(status: string) {
  switch (status) {
    case "likely_paid_off":
      return { label: "疑似回收", variant: "success" as const };
    case "reinforced":
      return { label: "持续强化", variant: "secondary" as const };
    case "archived":
      return { label: "已归档", variant: "outline" as const };
    default:
      return { label: "待回收", variant: "outline" as const };
  }
}

/**
 * 2026-08-31，作用：将强度、置信度和回收可能性转换为中文
 * 简要说明：未知英文枚举使用待确认兜底，中文原值直接保留
 */
function getLevelLabel(value: string | null): string {
  if (!value) return "—";
  if (/^[\u4e00-\u9fff]/.test(value)) return value;
  if (value === "high") return "较高";
  if (value === "medium") return "中等";
  if (value === "low") return "较低";
  return "待确认";
}

/**
 * 诊断页在 `200 null` 场景下需要稳定空态，避免用户看到空白成功页
 */
function EmptyDiagnosisState() {
  return (
    <DashboardCardShell
      title="诊断报告暂未生成"
      icon={<AlertCircle className="h-4 w-4" />}
      accent="chart-2"
      className="min-h-[240px]"
      bodyClassName="items-center justify-center gap-3 text-center"
    >
      <p className="text-sm text-text-muted">当前任务暂时还没有可展示的诊断结果。</p>
    </DashboardCardShell>
  );
}

/**
 * 伏笔追踪是独立查询，失败时必须显式告警，而不是静默吞掉
 */
function ForeshadowingThreadsErrorCard(props: { onRetry: () => void }) {
  return (
    <DashboardCardShell
      title="伏笔追踪加载失败"
      icon={<AlertCircle className="h-4 w-4" />}
      accent="chart-5"
      bodyClassName="items-center justify-center gap-3 text-center"
    >
      <p className="text-sm text-text-muted">伏笔线索暂时无法读取，请稍后重试。</p>
      <Button variant="outline" size="sm" onClick={props.onRetry}>
        重试
      </Button>
    </DashboardCardShell>
  );
}

/**
 * 2026-04-29，作用：展示独立于综合诊断正文的伏笔追踪结果
 * 简要说明：诊断正文为空时仍保留可用线索，并在文档流中展示筛选、轨迹和详情
 */
function ForeshadowingThreadsSection(props: { foreshadowingThreads: ForeshadowingThread[] }) {
  const [filter, setFilter] = useState<"all" | "open" | "reinforced" | "likely_paid_off" | "archived">("all");
  const [selectedSetupId, setSelectedSetupId] = useState<string | null>(props.foreshadowingThreads[0]?.setup_id ?? null);
  const counts = useMemo(() => {
    const result = { open: 0, reinforced: 0, likely_paid_off: 0, archived: 0 };
    props.foreshadowingThreads.forEach((thread) => {
      if (thread.status in result) result[thread.status as keyof typeof result] += 1;
    });
    return result;
  }, [props.foreshadowingThreads]);
  const visibleThreads = filter === "all"
    ? props.foreshadowingThreads
    : props.foreshadowingThreads.filter((thread) => thread.status === filter);
  const selectedThread =
    visibleThreads.find((thread) => thread.setup_id === selectedSetupId) ?? visibleThreads[0] ?? null;

  if (props.foreshadowingThreads.length === 0) {
    return (
      <div className="flex min-h-[240px] items-center justify-center rounded-lg border border-dashed border-border/60 bg-surface/50 px-6 text-center text-sm text-text-muted">
        当前任务暂无伏笔线索
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <AnalysisMetricStrip
        items={[
          { label: "待回收", value: counts.open },
          { label: "持续强化", value: counts.reinforced },
          { label: "疑似回收", value: counts.likely_paid_off },
          { label: "已归档", value: counts.archived },
        ]}
      />

      <AnalysisViewSwitcher
        value={filter}
        onValueChange={setFilter}
        label="伏笔状态筛选"
        options={[
          { value: "all", label: "全部" },
          { value: "open", label: "待回收" },
          { value: "reinforced", label: "持续强化" },
          { value: "likely_paid_off", label: "疑似回收" },
          { value: "archived", label: "已归档" },
        ]}
      />

      <div className="grid grid-cols-[minmax(0,1.35fr)_minmax(340px,0.65fr)] items-start gap-4">
        <div className="space-y-3">
          {visibleThreads.map((thread) => {
            const statusMeta = getThreadStatusMeta(thread.status);
            const isSelected = selectedThread?.setup_id === thread.setup_id;
            const chapterIds = thread.anchor_chapter_ids.length > 0
              ? thread.anchor_chapter_ids
              : [thread.first_chapter_id, thread.last_chapter_id];
            return (
              <button
                key={thread.setup_id}
                type="button"
                aria-pressed={isSelected}
                onClick={() => setSelectedSetupId(thread.setup_id)}
                className={cn(
                  "w-full rounded-lg border p-4 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/45",
                  isSelected ? "border-primary/35 bg-primary/5" : "border-border/70 bg-surface/70 hover:bg-surface-hover",
                )}
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant={statusMeta.variant}>{statusMeta.label}</Badge>
                      <span className="text-xs text-text-muted">{thread.setup_kind ?? "类型待确认"}</span>
                    </div>
                    <p className="mt-2 text-sm font-semibold leading-6 text-text">{thread.setup_summary}</p>
                    <p className="mt-1 text-xs text-text-muted">预计方向：{thread.expected_payoff_family ?? "待确认"}</p>
                  </div>
                  <div className="text-right text-xs text-text-muted">
                    <div>回收可能性</div>
                    <div className="mt-1 font-medium text-text">{getLevelLabel(thread.payoff_likelihood)}</div>
                  </div>
                </div>
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  {chapterIds.map((chapterId, index) => (
                    <span key={`${thread.setup_id}-${chapterId}-${index}`} className="rounded-full border border-border/60 px-2.5 py-1 text-xs text-text-muted">
                      第 {chapterId} 章 · {index === 0 ? "首次出现" : index === chapterIds.length - 1 ? "最近出现" : "再次出现"}
                    </span>
                  ))}
                </div>
              </button>
            );
          })}
          {visibleThreads.length === 0 ? (
            <div className="rounded-lg border border-dashed border-border/60 p-6 text-center text-sm text-text-muted">当前筛选下没有伏笔线索</div>
          ) : null}
        </div>

        {selectedThread ? (
          <aside className="rounded-lg border border-border/70 bg-surface/75 p-5" aria-label="伏笔详情">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={getThreadStatusMeta(selectedThread.status).variant}>{getThreadStatusMeta(selectedThread.status).label}</Badge>
              <Badge variant="outline">{selectedThread.setup_kind ?? "类型待确认"}</Badge>
            </div>
            <h2 className="mt-3 text-base font-semibold leading-7 text-text">{selectedThread.setup_summary}</h2>
            <dl className="mt-4 grid gap-3 text-sm">
              <div className="rounded-lg bg-surface-hover/55 p-3"><dt className="text-xs text-text-muted">预计回收方向</dt><dd className="mt-1 font-medium text-text">{selectedThread.expected_payoff_family ?? "待确认"}</dd></div>
              <div className="rounded-lg bg-surface-hover/55 p-3"><dt className="text-xs text-text-muted">最近判断依据</dt><dd className="mt-1 leading-6 text-text">{selectedThread.latest_reason ?? "暂无补充判断"}</dd></div>
              {selectedThread.latest_why_unresolved_now ? (
                <div className="rounded-lg bg-surface-hover/55 p-3"><dt className="text-xs text-text-muted">暂未回收原因</dt><dd className="mt-1 leading-6 text-text">{selectedThread.latest_why_unresolved_now}</dd></div>
              ) : null}
            </dl>
            <AnalysisDetails className="mt-4" description="强度、置信度、活跃状态与全部锚点">
              <dl className="grid grid-cols-1 gap-3 text-sm">
                <div><dt className="text-text-muted">线索强度</dt><dd className="mt-1 font-medium text-text">{getLevelLabel(selectedThread.strength)}</dd></div>
                <div><dt className="text-text-muted">判断置信度</dt><dd className="mt-1 font-medium text-text">{getLevelLabel(selectedThread.confidence)}</dd></div>
                <div><dt className="text-text-muted">跟踪状态</dt><dd className="mt-1 font-medium text-text">{selectedThread.active ? "继续跟踪" : "已经结束"}</dd></div>
                <div><dt className="text-text-muted">锚点章节</dt><dd className="mt-1 font-medium text-text">{selectedThread.anchor_chapter_ids.join("、") || "—"}</dd></div>
              </dl>
            </AnalysisDetails>
          </aside>
        ) : null}
      </div>
    </div>
  );
}

/**
 * 修改原因: 诊断页新增空态与台账错误分支后，仍保留独立 skeleton 以避免首屏闪烁
 */
function SkeletonGrid() {
  return (
    <div className="space-y-6">
      {/* 标题骨架屏 */}
      <div className="h-8 w-48 animate-pulse rounded bg-surface-hover" />

      {/* 评分卡骨架屏 */}
      <div className="grid grid-cols-4 gap-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Card key={i} className="h-[140px]">
            <CardContent className="p-5">
              <div className="space-y-3">
                <div className="h-4 w-20 animate-pulse rounded bg-surface-hover" />
                <div className="flex items-center gap-3">
                  <div className="h-14 w-14 animate-pulse rounded-full bg-surface-hover" />
                  <div className="h-6 w-16 animate-pulse rounded bg-surface-hover" />
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* 文本与图表骨架屏 */}
      <div className="grid grid-cols-2 gap-6">
        <Card className="h-[300px]">
          <CardContent className="p-5">
            <div className="space-y-3">
              <div className="h-5 w-24 animate-pulse rounded bg-surface-hover" />
              <div className="space-y-2">
                {Array.from({ length: 4 }).map((_, i) => (
                  <div key={i} className="h-4 w-full animate-pulse rounded bg-surface-hover" />
                ))}
              </div>
            </div>
          </CardContent>
        </Card>
        <Card className="h-[300px]">
          <CardContent className="p-5">
            <div className="space-y-3">
              <div className="h-5 w-24 animate-pulse rounded bg-surface-hover" />
              <div className="h-full animate-pulse rounded bg-surface-hover" />
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  主组件                                                             */
/* ------------------------------------------------------------------ */

/**
 * 2026-04-27，作用：展示作品综合诊断和伏笔追踪
 * 简要说明：综合诊断承载作品定位、价值表达和角色阵容，伏笔追踪承载线索状态与章节依据
 */
export function DiagnosisPage() {
  const { novelId } = useParams<{ novelId: string }>();
  const [searchParams] = useSearchParams();

  const urlTaskId = searchParams.get("task_id");

  // 2026-08-13 P1-2: 小说作用域任务守卫——跨小说切换后旧小说的任务
  // 不得用于新小说的查询/SSE（模式同 GraphPage）
  const { storeTaskId } = useNovelScopedTask(novelId, urlTaskId);

  // 数据获取
  const enabled = !!novelId && !!storeTaskId;

  const diagnosisQuery = useQuery({
    queryKey: ["results", novelId, storeTaskId, "diagnosis"],
    queryFn: () => getDiagnosis(novelId!, storeTaskId!),
    enabled,
    staleTime: STALE_TIME,
  });
  const foreshadowingThreadsQuery = useQuery({
    queryKey: ["results", novelId, storeTaskId, "foreshadowing-threads"],
    queryFn: () => getForeshadowingThreads(novelId!, storeTaskId!),
    enabled,
    staleTime: STALE_TIME,
  });

  const isLoading = enabled && diagnosisQuery.isLoading;
  const isAnalysisNotComplete =
    enabled &&
    (isAnalysisNotCompleteError(diagnosisQuery.error) || isAnalysisNotCompleteError(foreshadowingThreadsQuery.error));
  const analysisFailed =
    enabled &&
    (getAnalysisNotCompleteRunStatus(diagnosisQuery.error) === "failed" ||
      getAnalysisNotCompleteRunStatus(foreshadowingThreadsQuery.error) === "failed");
  const isDiagnosisError = enabled && diagnosisQuery.isError && !isAnalysisNotComplete;
  const isThreadsError = enabled && foreshadowingThreadsQuery.isError && !isAnalysisNotComplete;
  const hasNullDiagnosis =
    enabled &&
    diagnosisQuery.isFetched &&
    !diagnosisQuery.isLoading &&
    !diagnosisQuery.isError &&
    diagnosisQuery.data === null;

  const retryDiagnosis = () => {
    void diagnosisQuery.refetch();
  };
  const retryThreads = () => {
    void foreshadowingThreadsQuery.refetch();
  };

  const { data: diagnosis } = diagnosisQuery;
  const foreshadowMetric = diagnosis?.foreshadow_expectation ?? null;
  const foreshadowingThreads = foreshadowingThreadsQuery.data ?? [];
  const primaryGenreLabel = diagnosis?.genre_labels?.[0] ?? null;
  const [view, setView] = useState<"overview" | "foreshadowing">("overview");

  // ---------- 渲染 ----------

  return (
    <AnalysisWorkspace title={primaryGenreLabel ? `${primaryGenreLabel}诊断报告` : "诊断报告"} documentFlow>
      {/* 加载骨架屏 */}
      {isLoading && <SkeletonGrid />}

      {/* 错误状态 */}
      {isAnalysisNotComplete && !isLoading && (
        <AnalysisNotCompleteState
          title={analysisFailed ? "诊断分析任务已失败" : "诊断结果尚未完成"}
          description={
            analysisFailed
              ? "该分析任务已失败，诊断报告和伏笔追踪无法读取，请重新发起分析后再查看。"
              : "当前任务仍在分析中，诊断报告和伏笔追踪暂时不可读，请等待任务进入完成态后再查看。"
          }
          failed={analysisFailed}
        />
      )}
      {isDiagnosisError && !isLoading && (
        <DashboardCardShell
          title="诊断报告加载失败"
          icon={<AlertCircle className="h-4 w-4" />}
          accent="chart-5"
          className="min-h-[240px]"
          bodyClassName="items-center justify-center gap-3 text-center"
        >
          <p className="text-sm text-text-muted">当前任务的诊断数据暂时无法读取。</p>
          <Button variant="outline" size="sm" onClick={retryDiagnosis}>
            重试
          </Button>
        </DashboardCardShell>
      )}

      {/* 空状态 */}
      {hasNullDiagnosis && !isLoading && <EmptyDiagnosisState />}

      {/* 伏笔追踪兜底展示 */}
      {isThreadsError && !diagnosis && !isLoading && <ForeshadowingThreadsErrorCard onRetry={retryThreads} />}
      {foreshadowingThreads.length > 0 && !diagnosis && !isLoading && !isAnalysisNotComplete && (
        <div className="pb-6">
          <ForeshadowingThreadsSection foreshadowingThreads={foreshadowingThreads} />
        </div>
      )}

      {/* 主内容 */}
      {diagnosis && !isLoading && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
          className="space-y-4 pb-6"
        >
          <div className="flex items-center justify-between gap-3 rounded-lg border border-border/70 bg-surface/70 px-4 py-3">
            <div>
              <h1 className="text-base font-semibold text-text">{view === "overview" ? "综合诊断" : "伏笔追踪"}</h1>
              <p className="mt-1 text-sm text-text-muted">
                {view === "overview" ? "作品定位、价值表达、角色阵容与主题判断" : "线索状态、出现章节与最近判断依据"}
              </p>
            </div>
            <AnalysisViewSwitcher
              value={view}
              onValueChange={setView}
              label="诊断报告视图"
              options={[
                { value: "overview", label: "综合诊断", icon: FileText },
                { value: "foreshadowing", label: "伏笔追踪", icon: GitBranch },
              ]}
            />
          </div>

          {view === "overview" ? (
            <div className="space-y-4">
              <div className="grid grid-cols-[minmax(0,1.08fr)_minmax(0,0.92fr)] gap-4">
                <div className="grid grid-cols-2 gap-4">
                  <ScoreCard
                    title="伏笔回收预期"
                    type="percent"
                    value={foreshadowMetric != null ? foreshadowMetric * 100 : null}
                  />
                  <ScoreCard title="权力立场" type="score" score={diagnosis.power_stance_score} reason={diagnosis.power_stance_reason} />
                  <ScoreCard title="平民尊严" type="score" score={diagnosis.common_people_dignity} reason={diagnosis.dignity_reason} />
                  <ScoreCard title="文化深度" type="score" score={diagnosis.cultural_depth_score} reason={diagnosis.cultural_depth_reason} />
                </div>

                <div className="flex flex-col gap-4">
                  <DiagnosisHeader
                    genreLabels={diagnosis.genre_labels}
                    styleLabels={diagnosis.style_labels}
                    arcType={diagnosis.narrative_arc_type}
                  />
                  {diagnosis.diagnosis ? (
                    <DiagnosisText diagnosisText={diagnosis.diagnosis} className="min-h-[320px]" />
                  ) : (
                    <DashboardCardShell
                      title="综合诊断"
                      icon={<AlertCircle className="h-4 w-4" />}
                      accent="chart-2"
                      className="min-h-[240px]"
                      bodyClassName="items-center justify-center text-center"
                    >
                      <p className="text-sm text-text-muted">当前任务暂无综合诊断文本。</p>
                    </DashboardCardShell>
                  )}
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <ValueLogicCard
                  valueLogicType={diagnosis.value_logic_type}
                  valueLogicReason={diagnosis.value_logic_reason}
                  className="min-h-[260px]"
                />
                <CharacterCastCard
                  focusStructure={diagnosis.focus_structure ?? undefined}
                  focusCharacters={diagnosis.focus_characters}
                  coreCast={diagnosis.core_cast}
                  majorCast={diagnosis.main_characters}
                  className="min-h-[260px]"
                />
                <ArcScoresChart arcScores={diagnosis.arc_scores} className="min-h-[320px]" />
                <DashboardCardShell
                  title="主题标签"
                  icon={<Tags className="h-4 w-4" />}
                  accent="chart-4"
                  bodyClassName="gap-3"
                  className="min-h-[240px]"
                >
                  <div className="rounded-lg border border-border/60 bg-surface/70 p-4">
                    <TopicLabels labels={diagnosis.topic_labels} />
                  </div>
                </DashboardCardShell>
              </div>
            </div>
          ) : isThreadsError ? (
            <ForeshadowingThreadsErrorCard onRetry={retryThreads} />
          ) : foreshadowingThreadsQuery.isLoading ? (
            <div className="h-[320px] animate-pulse rounded-lg border border-border/60 bg-surface-hover" />
          ) : (
            <ForeshadowingThreadsSection foreshadowingThreads={foreshadowingThreads} />
          )}
        </motion.div>
      )}
    </AnalysisWorkspace>
  );
}
