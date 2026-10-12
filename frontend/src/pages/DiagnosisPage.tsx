import { useMemo, useState, type ReactNode } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { isAnalysisNotCompleteError, getAnalysisNotCompleteRunStatus } from "@/api/errorGuards";
import { getDiagnosis, getForeshadowingTrees } from "@/api/results";
import { useNovelScopedTask } from "@/hooks/useNovelScopedTask";
import { AnalysisNotCompleteState } from "@/components/common/AnalysisNotCompleteState";
import { AnalysisMetricStrip } from "@/components/common/AnalysisMetricStrip";
import { AnalysisViewSwitcher } from "@/components/common/AnalysisViewSwitcher";
import { PagedControls } from "@/components/common/PagedControls";
import { AnalysisWorkspace } from "@/components/layout/AnalysisWorkspace";
import { DashboardCardShell } from "@/components/common/DashboardCardShell";
import { DiagnosisHeader } from "@/components/diagnosis/DiagnosisHeader";
import { DiagnosisText } from "@/components/diagnosis/DiagnosisText";
import { ValueLogicCard } from "@/components/diagnosis/ValueLogicCard";
import { TopicLabels } from "@/components/diagnosis/TopicLabels";
import { CharacterCastCard } from "@/components/diagnosis/CharacterCastCard";
import { DiagnosisPagedText } from "@/components/diagnosis/DiagnosisPagedText";
import { useDiagnosisCapacity } from "@/components/diagnosis/useDiagnosisCapacity";
import { ArcScoresChart } from "@/components/charts/ArcScoresChart";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { AlertCircle, Tags } from "lucide-react";
import type { ForeshadowingTree } from "@/api/types";
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

interface OverviewMetric {
  title: string;
  value: string;
  reason: string | null | undefined;
}

function OverviewReasonCard({ metric }: { metric: OverviewMetric }) {
  return (
    <DashboardCardShell title={`${metric.title}依据`} accent="chart-2" className="h-full min-h-0" contentClassName="min-h-0 [&>div:first-child]:shrink-0" bodyClassName="min-h-0 flex-1">
      <DiagnosisPagedText key={metric.reason} text={metric.reason} label={`${metric.title}依据`} className="text-xs leading-5" />
    </DashboardCardShell>
  );
}

/** 先读评分与依据，再读综合正文，短卡片不承担整屏高度 */
function DiagnosisOverview({ metrics, labels, diagnosisText }: { metrics: OverviewMetric[]; labels: ReactNode; diagnosisText?: string | null }) {
  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      <div className="grid shrink-0 grid-cols-4 gap-3">
        {metrics.map((item) => (
          <div key={item.title} className="rounded-lg border border-border/70 bg-surface/75 px-4 py-2">
            <span className="block text-xs text-text-muted">{item.title}</span>
            <span className="mt-1 block text-xl font-semibold tabular-nums text-text">{item.value}</span>
          </div>
        ))}
      </div>
      <div className="shrink-0">{labels}</div>
      <DiagnosisText diagnosisText={diagnosisText} className="min-h-0 flex-1" />
      <div className="grid h-[180px] shrink-0 grid-cols-3 gap-3">
        {metrics.slice(1).map((metric) => <OverviewReasonCard key={metric.title} metric={metric} />)}
      </div>
    </div>
  );
}

/** 复用报告正文中已有的专题段落，未分段的报告保留综合正文入口 */
function getDiagnosisSection(text: string | null | undefined, topic: "cast" | "value") {
  const pattern = topic === "cast" ? /人物|角色/u : /主题|价值/u;
  const sections = (text ?? "").split(/(?=【[^】]+】)/u).filter(section => {
    const title = section.match(/^【([^】]+)】/u)?.[1];
    return title && pattern.test(title);
  });
  return { text: sections.length ? sections.map(section => section.trim()).join("\n\n") : text, title: sections.length ? (topic === "cast" ? "人物诊断" : "主题与价值诊断") : "综合诊断" };
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
function ForeshadowingTreesErrorCard(props: { onRetry: () => void }) {
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
function ForeshadowingTreesSection(props: { foreshadowingTrees: ForeshadowingTree[] }) {
  const [filter, setFilter] = useState<"all" | "open" | "reinforced" | "likely_paid_off">("all");
  const [selectedRootId, setSelectedRootId] = useState<string | null>(props.foreshadowingTrees[0]?.root_event_id ?? null);
  const [page, setPage] = useState(1);
  const { ref, capacity } = useDiagnosisCapacity(64, 0, 6);
  const counts = useMemo(() => {
    const result = { open: 0, reinforced: 0, likely_paid_off: 0 };
    props.foreshadowingTrees.forEach(tree => {
      if (tree.status in result) result[tree.status as keyof typeof result] += 1;
    });
    return result;
  }, [props.foreshadowingTrees]);
  const visibleTrees = filter === "all" ? props.foreshadowingTrees : props.foreshadowingTrees.filter(tree => tree.status === filter);
  const pageCount = Math.ceil(visibleTrees.length / capacity);
  const currentPage = Math.min(page, Math.max(pageCount, 1));
  const pageTrees = visibleTrees.slice((currentPage - 1) * capacity, currentPage * capacity);
  const selectedTree = visibleTrees.find(tree => tree.root_event_id === selectedRootId) ?? pageTrees[0] ?? null;
  const detailText = selectedTree ? [
    selectedTree.description,
    `最近判断依据：${selectedTree.latest_reason || "暂无补充判断"}`,
    selectedTree.latest_why_unresolved_now ? `暂未回收原因：${selectedTree.latest_why_unresolved_now}` : "",
    `锚点章节：${selectedTree.anchor_chapter_ids.join("、") || "—"}`,
  ].filter(Boolean).join(selectedTree.latest_reason || selectedTree.latest_why_unresolved_now ? "\n\n" : "\n") : "";
  const hasReason = !!(selectedTree?.latest_reason || selectedTree?.latest_why_unresolved_now);

  if (!props.foreshadowingTrees.length) {
    return <div className="flex h-full items-center justify-center rounded-lg border border-dashed border-border/60 text-sm text-text-muted">当前任务暂无伏笔线索</div>;
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      <div className="grid shrink-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-4">
        <AnalysisMetricStrip items={[
          { label: "待回收", value: counts.open },
          { label: "持续强化", value: counts.reinforced },
          { label: "疑似回收", value: counts.likely_paid_off },
        ]} className="grid-cols-3 [&>div]:px-3 [&>div]:py-1.5 [&>div>dd]:text-base" />
        <AnalysisViewSwitcher value={filter} onValueChange={value => { setFilter(value); setPage(1); }}
          label="伏笔状态筛选" options={[
            { value: "all", label: "全部" }, { value: "open", label: "待回收" },
            { value: "reinforced", label: "持续强化" }, { value: "likely_paid_off", label: "疑似回收" },
          ]} />
      </div>

      <section className="flex min-h-0 flex-1 flex-col gap-2" aria-label="伏笔线索列表">
        <div className="flex shrink-0 items-center justify-between text-xs text-text-muted">
          <h2 className="text-sm font-semibold text-text">伏笔线索 · {visibleTrees.length} 条</h2>
          {visibleTrees.length > 0 && <span>当前 {((currentPage - 1) * capacity) + 1}–{Math.min(currentPage * capacity, visibleTrees.length)} 条</span>}
        </div>
        <div className="grid shrink-0 grid-cols-[90px_minmax(0,1fr)_140px_88px_80px] gap-3 px-3 text-xs text-text-muted">
          <span>状态</span><span>线索</span><span>章节与锚点</span><span>回收可能性</span><span>线索强度</span>
        </div>
        <div ref={ref} className="min-h-0 flex-1 rounded-lg border border-border/70 bg-surface/70">
          {pageTrees.map(tree => {
            const status = getThreadStatusMeta(tree.status);
            return (
              <button key={tree.root_event_id} type="button" aria-pressed={selectedTree?.root_event_id === tree.root_event_id}
                aria-label={`${tree.description} · 回收可能性 ${getLevelLabel(tree.payoff_likelihood)}`}
                onClick={() => setSelectedRootId(tree.root_event_id)}
                className={cn("grid h-16 w-full grid-cols-[90px_minmax(0,1fr)_140px_88px_80px] items-center gap-3 border-b border-l-2 border-b-border/50 px-3 text-left text-xs first:rounded-t-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary/45",
                  selectedTree?.root_event_id === tree.root_event_id ? "border-l-primary bg-primary/10" : "border-l-transparent hover:bg-surface-hover")}>
                <span><Badge variant={status.variant}>{status.label}</Badge></span>
                <span data-diagnosis-preview className="line-clamp-2 text-sm leading-5 text-text">{tree.description}</span>
                <span className="text-text-muted">第 {tree.first_chapter_id} 至 {tree.last_chapter_id} 章 · {tree.anchor_chapter_ids.length} 个锚点</span>
                <span>{getLevelLabel(tree.payoff_likelihood)}</span><span>{getLevelLabel(tree.strength)}</span>
              </button>
            );
          })}
          {!visibleTrees.length && <p className="p-4 text-sm text-text-muted">当前筛选下没有伏笔线索</p>}
        </div>
        <div className="h-8 shrink-0"><PagedControls page={currentPage} pageCount={pageCount} onPageChange={next => {
          setPage(next);
          setSelectedRootId(visibleTrees[(next - 1) * capacity]?.root_event_id ?? null);
        }} label="伏笔线索" /></div>
      </section>

      {selectedTree && <aside aria-label="伏笔详情" className={cn("flex min-h-0 shrink-0 flex-col gap-2 rounded-lg border border-border/70 bg-surface/75 p-3", hasReason ? "h-[32%]" : "h-[132px]")}>
        <div className="flex shrink-0 items-center justify-between gap-4">
          <h2 className="text-sm font-semibold text-text">伏笔详情</h2>
          <dl className="flex items-center gap-4 text-xs">
            <div className="flex gap-2"><dt className="text-text-muted">线索强度</dt><dd>{getLevelLabel(selectedTree.strength)}</dd></div>
            <div className="flex gap-2"><dt className="text-text-muted">跟踪状态</dt><dd>{selectedTree.active ? "继续跟踪" : "已经结束"}</dd></div>
            <div className="flex gap-2"><dt className="text-text-muted">回收可能性</dt><dd>{getLevelLabel(selectedTree.payoff_likelihood)}</dd></div>
          </dl>
        </div>
        <DiagnosisPagedText key={selectedTree.root_event_id} text={detailText} label="伏笔判断" testId="foreshadowing-detail-passage" />
      </aside>}
    </div>
  );
}

/**
 * 修改原因: 诊断页新增空态与台账错误分支后，仍保留独立 skeleton 以避免首屏闪烁
 */
function SkeletonGrid() {
  return (
    <div className="flex h-full min-h-0 flex-col gap-4 overflow-hidden">
      {/* 标题骨架屏 */}
      <div className="h-8 w-48 animate-pulse rounded bg-surface-hover" />

      {/* 评分卡骨架屏 */}
      <div className="grid shrink-0 grid-cols-4 gap-4">
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
      <div className="grid min-h-0 flex-1 grid-cols-2 gap-6">
        <Card className="h-full min-h-0">
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
        <Card className="h-full min-h-0">
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
  const foreshadowingTreesQuery = useQuery({
    queryKey: ["results", novelId, storeTaskId, "foreshadowing-trees"],
    queryFn: () => getForeshadowingTrees(novelId!, storeTaskId!),
    enabled,
    staleTime: STALE_TIME,
  });

  const isLoading = enabled && diagnosisQuery.isLoading;
  const isAnalysisNotComplete =
    enabled &&
    (isAnalysisNotCompleteError(diagnosisQuery.error) || isAnalysisNotCompleteError(foreshadowingTreesQuery.error));
  const analysisFailed =
    enabled &&
    (getAnalysisNotCompleteRunStatus(diagnosisQuery.error) === "failed" ||
      getAnalysisNotCompleteRunStatus(foreshadowingTreesQuery.error) === "failed");
  const isDiagnosisError = enabled && diagnosisQuery.isError && !isAnalysisNotComplete;
  const isThreadsError = enabled && foreshadowingTreesQuery.isError && !isAnalysisNotComplete;
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
    void foreshadowingTreesQuery.refetch();
  };

  const { data: diagnosis } = diagnosisQuery;
  const foreshadowMetric = diagnosis?.foreshadow_expectation ?? null;
  const foreshadowingTrees = foreshadowingTreesQuery.data ?? [];
  const primaryGenreLabel = diagnosis?.genre_labels?.[0] ?? null;
  // ---------- 渲染 ----------

  return (
    <AnalysisWorkspace title={primaryGenreLabel ? `${primaryGenreLabel}诊断报告` : "诊断报告"}>
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
      {hasNullDiagnosis && !isLoading && !isThreadsError && foreshadowingTrees.length === 0 && <EmptyDiagnosisState />}

      {/* 伏笔追踪兜底展示 */}
      {isThreadsError && !diagnosis && !isLoading && <ForeshadowingTreesErrorCard onRetry={retryThreads} />}
      {foreshadowingTrees.length > 0 && !diagnosis && !isLoading && !isAnalysisNotComplete && (
        <AnalysisWorkspace.Tabs defaultValue="overview">
          <AnalysisWorkspace.Tab value="overview" label="综合概览">
            <EmptyDiagnosisState />
          </AnalysisWorkspace.Tab>
          <AnalysisWorkspace.Tab value="foreshadowing" label="伏笔追踪">
            <ForeshadowingTreesSection foreshadowingTrees={foreshadowingTrees} />
          </AnalysisWorkspace.Tab>
        </AnalysisWorkspace.Tabs>
      )}

      {/* 主内容 */}
      {diagnosis && !isLoading && (
        <AnalysisWorkspace.Tabs defaultValue="overview">
          <AnalysisWorkspace.Tab value="overview" label="综合概览">
            <DiagnosisOverview
              diagnosisText={diagnosis.diagnosis}
              metrics={[
                { title: "伏笔回收预期", value: foreshadowMetric != null ? `${Math.round(foreshadowMetric * 100)}%` : "—", reason: null },
                { title: "权力立场", value: diagnosis.power_stance_score != null ? `${diagnosis.power_stance_score}/5` : "—", reason: diagnosis.power_stance_reason },
                { title: "平民尊严", value: diagnosis.common_people_dignity != null ? `${diagnosis.common_people_dignity}/5` : "—", reason: diagnosis.dignity_reason },
                { title: "文化深度", value: diagnosis.cultural_depth_score != null ? `${diagnosis.cultural_depth_score}/5` : "—", reason: diagnosis.cultural_depth_reason },
              ]}
              labels={<DiagnosisHeader
                genreLabels={diagnosis.genre_labels}
                styleLabels={diagnosis.style_labels}
                arcType={diagnosis.narrative_arc_type}
              />}
            />
          </AnalysisWorkspace.Tab>

          <AnalysisWorkspace.Tab value="value-topic" label="价值主题">
            <div className="grid h-full min-h-0 grid-cols-[minmax(0,1.65fr)_minmax(0,1fr)] gap-4">
              <div className="flex min-h-0 flex-col gap-3">
                <ValueLogicCard
                  valueLogicType={diagnosis.value_logic_type}
                  valueLogicReason={diagnosis.value_logic_reason}
                  contextText={[
                    getDiagnosisSection(diagnosis.diagnosis, "value").text,
                    diagnosis.power_stance_reason && `【权力立场依据】\n${diagnosis.power_stance_reason}`,
                    diagnosis.dignity_reason && `【平民尊严依据】\n${diagnosis.dignity_reason}`,
                    diagnosis.cultural_depth_reason && `【文化深度依据】\n${diagnosis.cultural_depth_reason}`,
                  ].filter(Boolean).join("\n\n")}
                  className="min-h-0 flex-1"
                />
                <div data-testid="diagnosis-emotion-note" className="shrink-0 rounded-lg border border-border/60 bg-surface/70 px-4 py-2 text-xs leading-5 text-text-muted">
                  词典情绪均值：{diagnosis.emotion_avg != null ? diagnosis.emotion_avg.toFixed(8) : "—"}；
                  零信号字符占比：{diagnosis.lexicon_zero_hit_share != null
                    ? `${(diagnosis.lexicon_zero_hit_share * 100).toFixed(2)}%`
                    : "—"}。词典未命中不代表正文没有情绪。
                </div>
              </div>
                <DashboardCardShell
                  title={`主题标签 · ${diagnosis.topic_labels ? Object.keys(diagnosis.topic_labels).length : 0} 个`}
                  icon={<Tags className="h-4 w-4" />}
                  accent="chart-4"
                  className="h-full min-h-0"
                  contentClassName="min-h-0 [&>div:first-child]:shrink-0"
                  bodyClassName="min-h-0 flex-1 gap-2"
                >
                  <TopicLabels labels={diagnosis.topic_labels} />
                </DashboardCardShell>
            </div>
          </AnalysisWorkspace.Tab>

          <AnalysisWorkspace.Tab value="cast-structure" label="角色结构">
            <div className="flex h-full min-h-0 flex-col gap-3">
              <CharacterCastCard
                focusStructure={diagnosis.focus_structure ?? undefined}
                focusCharacters={diagnosis.focus_characters}
                coreCast={diagnosis.core_cast}
                majorCast={diagnosis.main_characters}
                className="shrink-0"
              />
              <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)] gap-4">
                <ArcScoresChart arcScores={diagnosis.arc_scores} className="h-full min-h-0" />
                <DiagnosisText diagnosisText={getDiagnosisSection(diagnosis.diagnosis, "cast").text} title={getDiagnosisSection(diagnosis.diagnosis, "cast").title} textClassName="text-base leading-8" className="h-full min-h-0" />
              </div>
            </div>
          </AnalysisWorkspace.Tab>

          <AnalysisWorkspace.Tab value="foreshadowing" label="伏笔追踪">
            {isThreadsError ? (
              <ForeshadowingTreesErrorCard onRetry={retryThreads} />
            ) : foreshadowingTreesQuery.isLoading ? (
              <div className="h-full animate-pulse rounded-lg border border-border/60 bg-surface-hover" />
            ) : (
              <ForeshadowingTreesSection foreshadowingTrees={foreshadowingTrees} />
            )}
          </AnalysisWorkspace.Tab>
        </AnalysisWorkspace.Tabs>
      )}
    </AnalysisWorkspace>
  );
}
