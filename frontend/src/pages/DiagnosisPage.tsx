import { useEffect } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { getDiagnosis, getForeshadowingThreads } from "@/api/results";
import { useNovelStore } from "@/store/novelStore";
import { PageContainer } from "@/components/layout/PageContainer";
import { NovelHeader } from "@/components/common/NovelHeader";
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
import { AlertCircle, GitBranch, Tags } from "lucide-react";

/* ------------------------------------------------------------------ */
/*  Constants                                                         */
/* ------------------------------------------------------------------ */

const STALE_TIME = 5 * 60 * 1000;

/**
 * 修改时间: 2026-04-26
 * 修改者: Codex
 * 任务: fix-diagnosis-review-findings
 * 修改原因: diagnosis 页现在会同时展示 thread ledger，
 * 需要把状态标签集中到一个 helper，避免页面分支和展示语义漂移。
 */
function getThreadStatusMeta(status: string) {
  switch (status) {
    case "likely_paid_off":
      return { label: "可能已回收", variant: "success" as const };
    case "reinforced":
      return { label: "已强化", variant: "secondary" as const };
    case "archived":
      return { label: "已归档", variant: "outline" as const };
    default:
      return { label: "进行中", variant: "outline" as const };
  }
}

/* ------------------------------------------------------------------ */
/*  State Cards                                                       */
/* ------------------------------------------------------------------ */

/**
 * 创建时间: 2026-04-26
 * 创建者: Codex
 * 任务: fix-diagnosis-review-findings
 * 说明: 诊断页在 `200 null` 场景下需要稳定空态，避免用户看到空白成功页。
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
 * 创建时间: 2026-04-26
 * 创建者: Codex
 * 任务: fix-diagnosis-review-findings
 * 说明: setup thread 台账是独立查询，失败时必须显式告警，而不是静默吞掉。
 */
function ForeshadowingThreadsErrorCard(props: { onRetry: () => void }) {
  return (
    <DashboardCardShell
      title="Setup 台账加载失败"
      icon={<AlertCircle className="h-4 w-4" />}
      accent="chart-5"
      bodyClassName="items-center justify-center gap-3 text-center"
    >
      <p className="text-sm text-text-muted">伏笔 setup 台账暂时无法读取，请稍后重试。</p>
      <Button variant="outline" size="sm" onClick={props.onRetry}>
        重试台账
      </Button>
    </DashboardCardShell>
  );
}

/**
 * 创建时间: 2026-04-26
 * 创建者: Codex
 * 任务: fix-diagnosis-ledger-fallback
 * 说明: setup 台账是独立于云端 diagnosis 的主链结果；
 * 即便 diagnosis 为空，只要 ledger 已可用，也应该继续对用户可见。
 */
function ForeshadowingThreadsSection(props: {
  foreshadowingThreads: Array<{
    setup_id: string;
    first_chunk_id: number;
    last_chunk_id: number;
    anchor_chunk_ids: number[];
    setup_summary: string;
    setup_kind: string;
    expected_payoff_family: string;
    payoff_likelihood: string;
    strength: string;
    status: string;
    latest_reason?: string | null;
  }>;
}) {
  return (
    <DashboardCardShell
      title="Setup 台账"
      icon={<GitBranch className="h-4 w-4" />}
      accent="chart-2"
      bodyClassName="gap-3"
    >
      <div className="grid grid-cols-1 gap-3">
        {props.foreshadowingThreads.map((thread) => {
          const statusMeta = getThreadStatusMeta(thread.status);
          return (
            <div
              key={thread.setup_id}
              className="rounded-2xl border border-border/70 bg-surface/75 p-4"
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="space-y-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant={statusMeta.variant}>{statusMeta.label}</Badge>
                    <Badge variant="outline">{thread.setup_kind}</Badge>
                    <Badge variant="outline">{thread.expected_payoff_family}</Badge>
                  </div>
                  <p className="text-sm font-semibold text-text">{thread.setup_summary}</p>
                </div>
                <div className="text-right text-xs text-text-muted">
                  <div>首次出现 Chunk {thread.first_chunk_id}</div>
                  <div>最近命中 Chunk {thread.last_chunk_id}</div>
                </div>
              </div>
              <div className="mt-3 grid grid-cols-1 gap-2 text-xs text-text-muted md:grid-cols-3">
                <div>
                  <span className="font-medium text-text">回收预期：</span>
                  {thread.payoff_likelihood}
                </div>
                <div>
                  <span className="font-medium text-text">强度：</span>
                  {thread.strength}
                </div>
                <div>
                  <span className="font-medium text-text">锚点 Chunk：</span>
                  {thread.anchor_chunk_ids.join(", ")}
                </div>
              </div>
              {thread.latest_reason && (
                <p className="mt-3 text-sm text-text-muted">{thread.latest_reason}</p>
              )}
            </div>
          );
        })}
      </div>
    </DashboardCardShell>
  );
}

/**
 * 修改时间: 2026-04-26
 * 修改者: Codex
 * 任务: fix-diagnosis-review-findings
 * 修改原因: 诊断页新增空态与台账错误分支后，仍保留独立 skeleton 以避免首屏闪烁。
 */
function SkeletonGrid() {
  return (
    <div className="space-y-6">
      {/* Header skeleton */}
      <div className="h-8 w-48 animate-pulse rounded bg-surface-hover" />

      {/* Score cards skeleton */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
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

      {/* Text and chart skeleton */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
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
/*  Main Component                                                    */
/* ------------------------------------------------------------------ */

/**
 * 2026-04-27，任务：protagonist-focus-contract
 * 修改原因：诊断页角色阵容展示改为焦点结构合同，允许单主角、双主角与群像三种结果稳定渲染。
 */
export function DiagnosisPage() {
  const { novelId } = useParams<{ novelId: string }>();
  const [searchParams] = useSearchParams();
  const { currentTaskId, setNovel, setTask } = useNovelStore();

  const urlTaskId = searchParams.get("task_id");

  // Sync novelId to store on mount; initialize task from URL if present
  useEffect(() => {
    if (novelId) {
      setNovel(novelId);
      if (urlTaskId) {
        setTask(urlTaskId);
      }
    }
  }, [novelId, urlTaskId, setNovel, setTask]);

  // Data fetching
  const enabled = !!novelId && !!currentTaskId;

  const diagnosisQuery = useQuery({
    queryKey: ["results", novelId, currentTaskId, "diagnosis"],
    queryFn: () => getDiagnosis(novelId!, currentTaskId!),
    enabled,
    staleTime: STALE_TIME,
  });
  const foreshadowingThreadsQuery = useQuery({
    queryKey: ["results", novelId, currentTaskId, "foreshadowing-threads"],
    queryFn: () => getForeshadowingThreads(novelId!, currentTaskId!),
    enabled,
    staleTime: STALE_TIME,
  });

  const isLoading = enabled && diagnosisQuery.isLoading;
  const isDiagnosisError = enabled && diagnosisQuery.isError;
  const isThreadsError = enabled && foreshadowingThreadsQuery.isError;
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

  // ---------- Render ----------

  return (
    <PageContainer>
      {/* Header */}
      <NovelHeader
        title={diagnosis?.narrative_type ? `${diagnosis.narrative_type}诊断报告` : "诊断报告"}
        className="mb-6"
      />

      {/* Loading skeleton */}
      {isLoading && <SkeletonGrid />}

      {/* Error state */}
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

      {/* Empty state */}
      {hasNullDiagnosis && !isLoading && <EmptyDiagnosisState />}

      {/* Ledger fallback */}
      {isThreadsError && !isLoading && <ForeshadowingThreadsErrorCard onRetry={retryThreads} />}
      {foreshadowingThreads.length > 0 && !isLoading && <ForeshadowingThreadsSection foreshadowingThreads={foreshadowingThreads} />}

      {/* Main content */}
      {diagnosis && !isLoading && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
          className="space-y-6"
        >
          {/* Diagnosis Header */}
          <DiagnosisHeader
            narrativeType={diagnosis.narrative_type}
            arcType={diagnosis.narrative_arc_type}
          />

          {/* Score Cards Row */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <ScoreCard
              title="伏笔回收预期"
              type="percent"
              value={foreshadowMetric != null ? foreshadowMetric * 100 : null}
              reason="基于 setup thread ledger 的加权估计，不是严格全文事实回收率。"
            />
            <ScoreCard
              title="权力立场"
              type="score"
              score={diagnosis.power_stance_score}
              reason={diagnosis.power_stance_reason}
            />
            <ScoreCard
              title="平民尊严"
              type="score"
              score={diagnosis.common_people_dignity}
              reason={diagnosis.dignity_reason}
            />
            <ScoreCard
              title="文化深度"
              type="score"
              score={diagnosis.cultural_depth_score}
              reason={diagnosis.cultural_depth_reason}
            />
          </div>

          {/* 预留诊断文本区域 */}
          {diagnosis.diagnosis && <DiagnosisText diagnosisText={diagnosis.diagnosis} />}

          {/* ArcScoresChart */}
          {diagnosis.arc_scores && Object.keys(diagnosis.arc_scores).length > 0 && (
            <ArcScoresChart arcScores={diagnosis.arc_scores} />
          )}

          {/* Value Logic and Character Cast */}
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <ValueLogicCard
              valueLogicType={diagnosis.value_logic_type}
              valueLogicReason={diagnosis.value_logic_reason}
            />
            <CharacterCastCard
              focusStructure={diagnosis.focus_structure}
              focusCharacters={diagnosis.focus_characters}
              coreCast={diagnosis.core_cast}
              majorCast={diagnosis.main_characters}
            />
          </div>

          {/* Topic Labels */}
          {diagnosis.topic_labels && diagnosis.topic_labels.length > 0 && (
            <DashboardCardShell
              title="主题标签"
              icon={<Tags className="h-4 w-4" />}
              accent="chart-4"
              bodyClassName="gap-3"
            >
              <div className="rounded-2xl border border-border/60 bg-surface/70 p-4">
                <TopicLabels labels={diagnosis.topic_labels} />
              </div>
            </DashboardCardShell>
          )}
        </motion.div>
      )}
    </PageContainer>
  );
}
