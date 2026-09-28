import { useMemo, useState, type ReactNode } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { isAnalysisNotCompleteError, getAnalysisNotCompleteRunStatus } from "@/api/errorGuards";
import { getDiagnosis, getForeshadowingTrees } from "@/api/results";
import { useNovelScopedTask } from "@/hooks/useNovelScopedTask";
import { useCompactAnalysisViewport } from "@/hooks/useCompactAnalysisViewport";
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
import { ArcScoresChart } from "@/components/charts/ArcScoresChart";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { AlertCircle, Tags } from "lucide-react";
import type { ForeshadowingTree } from "@/api/types";
import { cn } from "@/lib/cn";
import { paginateText } from "@/lib/paginateText";

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
  const [page, setPage] = useState(1);
  const passages = paginateText(metric.reason ?? "", 220);
  const currentPage = Math.min(page, Math.max(passages.length, 1));

  return (
    <DashboardCardShell title={`${metric.title}依据`} accent="chart-2" className="min-h-0" contentClassName="flex h-full flex-col" bodyClassName="min-h-0 flex-1 gap-3">
      <p className="whitespace-pre-wrap text-xs leading-6 text-text-muted">{passages[currentPage - 1] ?? "暂无补充依据"}</p>
      <div className="mt-auto"><PagedControls page={currentPage} pageCount={passages.length} onPageChange={setPage} label={`${metric.title}依据`} /></div>
    </DashboardCardShell>
  );
}

/** 四项评分和三段依据分别占据整行与三列，不再让标签独占半页。 */
function DiagnosisOverview({ metrics, labels }: { metrics: OverviewMetric[]; labels: ReactNode }) {
  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      <div className="grid grid-cols-4 gap-3">
        {metrics.map((item) => (
          <div key={item.title} className="rounded-lg border border-border/70 bg-surface/75 px-4 py-3">
            <span className="block text-xs text-text-muted">{item.title}</span>
            <span className="mt-1 block text-xl font-semibold tabular-nums text-text">{item.value}</span>
          </div>
        ))}
      </div>
      <div className="shrink-0">{labels}</div>
      <div className="grid min-h-0 flex-1 grid-cols-3 gap-3">
        {metrics.slice(1).map((metric) => <OverviewReasonCard key={metric.title} metric={metric} />)}
      </div>
    </div>
  );
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
  const [detailPage, setDetailPage] = useState(1);
  const [detailView, setDetailView] = useState<"reason" | "tracking">("reason");
  const counts = useMemo(() => {
    const result = { open: 0, reinforced: 0, likely_paid_off: 0 };
    props.foreshadowingTrees.forEach((tree) => {
      if (tree.status in result) result[tree.status as keyof typeof result] += 1;
    });
    return result;
  }, [props.foreshadowingTrees]);
  const visibleTrees = filter === "all"
    ? props.foreshadowingTrees
    : props.foreshadowingTrees.filter((tree) => tree.status === filter);
  const pageCount = Math.ceil(visibleTrees.length / 2);
  const currentPage = Math.min(page, Math.max(pageCount, 1));
  const pageTrees = visibleTrees.slice((currentPage - 1) * 2, currentPage * 2);
  const selectedTree =
    pageTrees.find((tree) => tree.root_event_id === selectedRootId) ?? pageTrees[0] ?? null;
  const detailPassages = paginateText([
    selectedTree?.latest_reason ? `最近判断依据：${selectedTree.latest_reason}` : "最近判断依据：暂无补充判断",
    selectedTree?.latest_why_unresolved_now ? `暂未回收原因：${selectedTree.latest_why_unresolved_now}` : "",
  ].filter(Boolean).join("\n\n"), 100);
  const currentDetailPage = Math.min(detailPage, Math.max(detailPassages.length, 1));

  if (props.foreshadowingTrees.length === 0) {
    return (
      <div className="flex min-h-[240px] items-center justify-center rounded-lg border border-dashed border-border/60 bg-surface/50 px-6 text-center text-sm text-text-muted">
        当前任务暂无伏笔线索
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-4">
      <AnalysisMetricStrip
        items={[
          { label: "待回收", value: counts.open },
          { label: "持续强化", value: counts.reinforced },
          { label: "疑似回收", value: counts.likely_paid_off },
        ]}
        className="grid-cols-3 [&>div]:px-3 [&>div]:py-1.5 [&>div>dd]:text-base"
      />

      <AnalysisViewSwitcher
        value={filter}
        onValueChange={(value) => { setFilter(value); setPage(1); setDetailPage(1); }}
        label="伏笔状态筛选"
        options={[
          { value: "all", label: "全部" },
          { value: "open", label: "待回收" },
          { value: "reinforced", label: "持续强化" },
          { value: "likely_paid_off", label: "疑似回收" },
        ]}
      />

      <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1.1fr)_minmax(0,.9fr)] gap-4">
        <div className="flex min-h-0 flex-col gap-2">
          {pageTrees.map((tree) => {
            const statusMeta = getThreadStatusMeta(tree.status);
            const isSelected = selectedTree?.root_event_id === tree.root_event_id;
            return (
              <button
                key={tree.root_event_id}
                type="button"
                aria-pressed={isSelected}
                onClick={() => { setSelectedRootId(tree.root_event_id); setDetailPage(1); }}
                className={cn(
                  "w-full rounded-lg border p-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/45",
                  isSelected ? "border-primary/35 bg-primary/5" : "border-border/70 bg-surface/70 hover:bg-surface-hover",
                )}
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant={statusMeta.variant}>{statusMeta.label}</Badge>
                    </div>
                    <p className="mt-2 text-sm font-semibold leading-6 text-text">{tree.description}</p>
                  </div>
                  <div className="text-right text-xs text-text-muted">
                    <div>回收可能性</div>
                    <div className="mt-1 font-medium text-text">{getLevelLabel(tree.payoff_likelihood)}</div>
                  </div>
                </div>
                <p className="mt-2 text-xs text-text-muted">第 {tree.first_chapter_id} 至 {tree.last_chapter_id} 章 · {tree.anchor_chapter_ids.length} 个锚点</p>
              </button>
            );
          })}
          {visibleTrees.length === 0 ? (
            <div className="rounded-lg border border-dashed border-border/60 p-6 text-center text-sm text-text-muted">当前筛选下没有伏笔线索</div>
          ) : null}
          <PagedControls page={currentPage} pageCount={pageCount} onPageChange={(nextPage) => { setPage(nextPage); setDetailPage(1); }} label="伏笔线索" />
        </div>

        {selectedTree ? (
          <aside className="min-h-0 rounded-lg border border-border/70 bg-surface/75 p-4" aria-label="伏笔详情">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={getThreadStatusMeta(selectedTree.status).variant}>{getThreadStatusMeta(selectedTree.status).label}</Badge>
            </div>
            <h2 className="mt-2 text-base font-semibold leading-6 text-text">{selectedTree.description}</h2>
            <AnalysisViewSwitcher value={detailView} onValueChange={setDetailView} label="伏笔详情内容" className="mt-3" options={[
              { value: "reason", label: "判断依据" },
              { value: "tracking", label: "跟踪信息" },
            ]} />
            {detailView === "reason" ? (
              <>
                <div className="mt-3 rounded-lg bg-surface-hover/55 p-3">
                  <p className="whitespace-pre-wrap text-sm leading-6 text-text">{detailPassages[currentDetailPage - 1]}</p>
                  <PagedControls page={currentDetailPage} pageCount={detailPassages.length} onPageChange={setDetailPage} label="伏笔判断" />
                </div>
                <dl className="mt-3 grid grid-cols-2 gap-2 text-xs">
                  <div className="rounded-lg border border-border/60 p-2"><dt className="text-text-muted">线索强度</dt><dd className="mt-1 font-medium text-text">{getLevelLabel(selectedTree.strength)}</dd></div>
                  <div className="rounded-lg border border-border/60 p-2"><dt className="text-text-muted">跟踪状态</dt><dd className="mt-1 font-medium text-text">{selectedTree.active ? "继续跟踪" : "已经结束"}</dd></div>
                  <div className="col-span-2 rounded-lg border border-border/60 p-2"><dt className="text-text-muted">锚点章节</dt><dd className="mt-1 font-medium text-text">{selectedTree.anchor_chapter_ids.join("、") || "—"}</dd></div>
                </dl>
              </>
            ) : (
              <dl className="mt-3 grid gap-2 text-sm">
                <div><dt className="text-text-muted">线索强度</dt><dd className="font-medium text-text">{getLevelLabel(selectedTree.strength)}</dd></div>
                <div><dt className="text-text-muted">跟踪状态</dt><dd className="font-medium text-text">{selectedTree.active ? "继续跟踪" : "已经结束"}</dd></div>
                <div><dt className="text-text-muted">锚点章节</dt><dd className="font-medium text-text">{selectedTree.anchor_chapter_ids.join("、") || "—"}</dd></div>
              </dl>
            )}
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
  const compact = useCompactAnalysisViewport();

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
            <div className="grid h-full min-h-0 grid-cols-[minmax(0,1.08fr)_minmax(0,0.92fr)] gap-4">
              {diagnosis.diagnosis ? (
                <DiagnosisText diagnosisText={diagnosis.diagnosis} className="h-full min-h-0" />
              ) : (
                <DashboardCardShell
                  title="综合诊断"
                  icon={<AlertCircle className="h-4 w-4" />}
                  accent="chart-2"
                  className="h-full min-h-0"
                  bodyClassName="items-center justify-center text-center"
                >
                  <p className="text-sm text-text-muted">当前任务暂无综合诊断文本。</p>
                </DashboardCardShell>
              )}
              <div className={compact ? "flex min-h-0 flex-col gap-2" : "flex min-h-0 flex-col gap-4"}>
                <ValueLogicCard
                  valueLogicType={diagnosis.value_logic_type}
                  valueLogicReason={diagnosis.value_logic_reason}
                  className="shrink-0"
                />
                <DashboardCardShell
                  title={`主题标签 · ${diagnosis.topic_labels ? Object.keys(diagnosis.topic_labels).length : 0} 个`}
                  icon={<Tags className="h-4 w-4" />}
                  accent="chart-4"
                  contentClassName={compact ? "gap-1 p-2" : "gap-2 p-3"}
                  bodyClassName="gap-2"
                  className="shrink-0"
                >
                  <div className={compact ? "rounded-lg border border-border/60 bg-surface/70 p-2" : "rounded-lg border border-border/60 bg-surface/70 p-3"}>
                    <TopicLabels labels={diagnosis.topic_labels} />
                  </div>
                </DashboardCardShell>
                <div data-testid="diagnosis-emotion-note" className="rounded-lg border border-border/60 bg-surface/70 px-3 py-2 text-xs text-text-muted">
                  词典情绪均值：{diagnosis.emotion_avg != null ? diagnosis.emotion_avg.toFixed(8) : "—"}；
                  零信号字符占比：{diagnosis.lexicon_zero_hit_share != null
                    ? `${(diagnosis.lexicon_zero_hit_share * 100).toFixed(2)}%`
                    : "—"}。词典未命中不代表正文没有情绪。
                </div>
              </div>
            </div>
          </AnalysisWorkspace.Tab>

          <AnalysisWorkspace.Tab value="cast-structure" label="角色结构">
            <div className="grid h-full min-h-0 grid-cols-2 gap-4">
              <CharacterCastCard
                focusStructure={diagnosis.focus_structure ?? undefined}
                focusCharacters={diagnosis.focus_characters}
                coreCast={diagnosis.core_cast}
                majorCast={diagnosis.main_characters}
                className="h-full min-h-0"
              />
              <ArcScoresChart arcScores={diagnosis.arc_scores} className="h-full min-h-0" />
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
