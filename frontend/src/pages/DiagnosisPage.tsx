import { useParams, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { isAnalysisNotCompleteError, getAnalysisNotCompleteRunStatus } from "@/api/errorGuards";
import { getDiagnosis, getForeshadowingThreads } from "@/api/results";
import { useNovelScopedTask } from "@/hooks/useNovelScopedTask";
import { AnalysisNotCompleteState } from "@/components/common/AnalysisNotCompleteState";
import { AnalysisWorkspace } from "@/components/layout/AnalysisWorkspace";
import { DashboardCardShell } from "@/components/common/DashboardCardShell";
import { ScoreCard } from "@/components/common/ScoreCard";
import { DiagnosisHeader } from "@/components/diagnosis/DiagnosisHeader";
import { DiagnosisText } from "@/components/diagnosis/DiagnosisText";
import { ValueLogicCard } from "@/components/diagnosis/ValueLogicCard";
import { TopicLabels } from "@/components/diagnosis/TopicLabels";
import { CharacterCastCard } from "@/components/diagnosis/CharacterCastCard";
import { ArcScoresChart } from "@/components/charts/ArcScoresChart";
import { hasCompleteFocusContract } from "@/lib/diagnosisContract";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { AlertCircle, GitBranch, Tags } from "lucide-react";

const STALE_TIME = 5 * 60 * 1000;

/** 统一 diagnosis thread 状态到标签文案 */
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
 * diagnosis 页一旦拿到缺焦点合同的半成品 payload，就不能再按正常诊断报告渲染；
 * 这里显式提示用户该任务需要重跑，同时允许下方 setup ledger 继续独立展示
 */
function IncompleteDiagnosisContractState() {
  return (
    <DashboardCardShell
      title="诊断结果需要重跑"
      icon={<AlertCircle className="h-4 w-4" />}
      accent="chart-5"
      className="min-h-[240px]"
      bodyClassName="items-center justify-center gap-3 text-center"
    >
      <p className="text-sm text-text-muted">
        当前任务缺少完整的焦点结构 diagnosis，请重新分析该任务后再查看正式诊断报告。
      </p>
    </DashboardCardShell>
  );
}

/**
 * setup thread 台账是独立查询，失败时必须显式告警，而不是静默吞掉
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
 * setup 台账是独立于云端 diagnosis 的主链结果；
 * 即便 diagnosis 为空，只要 ledger 已可用，也应该继续对用户可见
 *
 * 2026-04-29，任务：诊断页单屏工作台修正
 * 修改原因：Setup 台账在 tab 面板内不能依赖整页滚动，改为卡片内部列表滚动，避免底部被 panel 裁剪
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
      className="flex h-full min-h-[240px] flex-col"
      contentClassName="flex h-full flex-col"
      bodyClassName="min-h-0 flex-1 gap-3"
    >
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 overflow-y-auto pr-1">
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
 * 修改原因: 诊断页新增空态与台账错误分支后，仍保留独立 skeleton 以避免首屏闪烁
 */
function SkeletonGrid() {
  return (
    <div className="space-y-6">
      {/* 标题骨架屏 */}
      <div className="h-8 w-48 animate-pulse rounded bg-surface-hover" />

      {/* 评分卡骨架屏 */}
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

      {/* 文本与图表骨架屏 */}
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
/*  主组件                                                             */
/* ------------------------------------------------------------------ */

/**
 * 2026-04-27，任务：protagonist-focus-contract
 * 修改原因：诊断页角色阵容展示改为焦点结构合同，允许单主角、双主角与群像三种结果稳定渲染
 *
 * 2026-04-28，任务：分析详情页单屏 Tabs 改造
 * 修改原因：诊断页内容拆成摘要、价值角色、Arc主题和台账四个 tab，统一交给单屏工作区编排
 *
 * 2026-04-29，任务：诊断页信息面收口
 * 修改原因：诊断页原先 4 个 tab 过于分散，除 Setup 台账外其余内容收口为 2 个更饱满的信息面
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
  const hasFocusContract = hasCompleteFocusContract(diagnosis);
  const foreshadowMetric = diagnosis?.foreshadow_expectation ?? null;
  const foreshadowingThreads = foreshadowingThreadsQuery.data ?? [];
  const primaryGenreLabel = diagnosis?.genre_labels?.[0] ?? null;
  const hasIncompleteDiagnosisContract =
    enabled &&
    diagnosisQuery.isFetched &&
    !diagnosisQuery.isLoading &&
    !diagnosisQuery.isError &&
    diagnosis != null &&
    !hasFocusContract;

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
              ? "该分析任务已失败，诊断报告和 setup 台账无法读取，请重新发起分析后再查看。"
              : "当前任务仍在分析中，诊断报告和 setup 台账暂时不可读，请等待任务进入完成态后再查看。"
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
      {hasIncompleteDiagnosisContract && !isLoading && <IncompleteDiagnosisContractState />}

      {/* 台账兜底展示 */}
      {isThreadsError && !isLoading && <ForeshadowingThreadsErrorCard onRetry={retryThreads} />}
      {foreshadowingThreads.length > 0 && !diagnosis && !isLoading && !isAnalysisNotComplete && (
        <div className="min-h-0">
          <ForeshadowingThreadsSection foreshadowingThreads={foreshadowingThreads} />
        </div>
      )}

      {/* 主内容 */}
      {diagnosis && hasFocusContract && !isLoading && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
          className="flex min-h-0 flex-1 flex-col"
        >
          {/*
            2026-04-28，任务：分析详情页单屏 Tabs 改造
            修改原因：诊断报告内容增长最快，改为摘要优先的 tab 结构，由单屏工作区统一约束边界。
          */}
          <AnalysisWorkspace.Tabs defaultValue="summary">
            <AnalysisWorkspace.Tab value="summary" label="诊断摘要">
              <div className="grid h-full min-h-0 gap-4 xl:grid-cols-[minmax(520px,1.08fr)_minmax(0,0.92fr)]">
                <div className="grid min-h-0 auto-rows-fr grid-cols-1 gap-4 md:grid-cols-2">
                  <ScoreCard
                    title="伏笔回收预期"
                    type="percent"
                    value={foreshadowMetric != null ? foreshadowMetric * 100 : null}
                  />
                  <ScoreCard title="权力立场" type="score" score={diagnosis.power_stance_score} reason={diagnosis.power_stance_reason} />
                  <ScoreCard title="平民尊严" type="score" score={diagnosis.common_people_dignity} reason={diagnosis.dignity_reason} />
                  <ScoreCard title="文化深度" type="score" score={diagnosis.cultural_depth_score} reason={diagnosis.cultural_depth_reason} />
                </div>

                <div className="flex min-h-0 flex-col gap-4">
                  <DiagnosisHeader
                    genreLabels={diagnosis.genre_labels}
                    styleLabels={diagnosis.style_labels}
                    arcType={diagnosis.narrative_arc_type}
                  />
                  {diagnosis.diagnosis ? (
                    <DiagnosisText diagnosisText={diagnosis.diagnosis} className="min-h-[320px] flex-1" />
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
            </AnalysisWorkspace.Tab>
            <AnalysisWorkspace.Tab value="insights" label="价值与主题">
              <div className="grid h-full min-h-0 auto-rows-fr grid-cols-1 gap-4 lg:grid-cols-2">
                <ValueLogicCard
                  valueLogicType={diagnosis.value_logic_type}
                  valueLogicReason={diagnosis.value_logic_reason}
                  className="h-full min-h-[260px]"
                />
                <CharacterCastCard
                  focusStructure={diagnosis.focus_structure}
                  focusCharacters={diagnosis.focus_characters}
                  coreCast={diagnosis.core_cast}
                  majorCast={diagnosis.main_characters}
                  className="h-full min-h-[260px]"
                />
                <ArcScoresChart arcScores={diagnosis.arc_scores} className="h-full min-h-[320px]" />
                <DashboardCardShell
                  title="主题标签"
                  icon={<Tags className="h-4 w-4" />}
                  accent="chart-4"
                  contentClassName="flex h-full flex-col"
                  bodyClassName="min-h-0 flex-1 gap-3"
                  className="h-full min-h-[240px]"
                >
                  <div className="min-h-0 flex-1 rounded-2xl border border-border/60 bg-surface/70 p-4">
                    <TopicLabels labels={diagnosis.topic_labels} />
                  </div>
                </DashboardCardShell>
              </div>
            </AnalysisWorkspace.Tab>
            <AnalysisWorkspace.Tab value="threads" label="Setup 台账">
              <div className="h-full min-h-0">
                {foreshadowingThreads.length > 0 ? (
                  <ForeshadowingThreadsSection foreshadowingThreads={foreshadowingThreads} />
                ) : (
                  <DashboardCardShell
                    title="Setup 台账"
                    icon={<GitBranch className="h-4 w-4" />}
                    accent="chart-2"
                    className="min-h-[240px]"
                    bodyClassName="items-center justify-center text-center"
                  >
                    <p className="text-sm text-text-muted">当前任务暂无 setup 台账记录。</p>
                  </DashboardCardShell>
                )}
              </div>
            </AnalysisWorkspace.Tab>
          </AnalysisWorkspace.Tabs>
        </motion.div>
      )}
    </AnalysisWorkspace>
  );
}
