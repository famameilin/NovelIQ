import { useEffect } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { isAnalysisNotCompleteError, getAnalysisNotCompleteRunStatus } from "@/api/errorGuards";
import { getCharacters, getDiagnosis } from "@/api/results";
import { useNovelStore } from "@/store/novelStore";
import { AnalysisNotCompleteState } from "@/components/common/AnalysisNotCompleteState";
import { AnalysisWorkspace } from "@/components/layout/AnalysisWorkspace";
import { DashboardCardShell } from "@/components/common/DashboardCardShell";
import { CharacterRankingBar } from "@/components/charts/CharacterRankingBar";
import { RoleFunctionPie } from "@/components/charts/RoleFunctionPie";
import { CharacterTable } from "@/components/characters/CharacterTable";
import { FocusCastCard } from "@/components/characters/FocusCastCard";
import { hasCompleteFocusContract } from "@/lib/diagnosisContract";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { AlertCircle, Users } from "lucide-react";

const STALE_TIME = 5 * 60 * 1000;

function SkeletonGrid() {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="space-y-6"
    >
      {/* 排行条骨架屏 */}
      <Card variant="elevated" className="rounded-xl h-[460px] overflow-hidden">
        <CardContent className="p-5">
          <div className="space-y-3">
            <div className="h-5 w-28 animate-pulse rounded bg-surface-hover" />
            <div className="h-[400px] animate-pulse rounded bg-surface-hover" />
          </div>
        </CardContent>
      </Card>

      {/* 饼图与主角卡片骨架屏 */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card variant="elevated" className="rounded-xl h-[340px] overflow-hidden">
          <CardContent className="p-5">
            <div className="space-y-3">
              <div className="h-5 w-28 animate-pulse rounded bg-surface-hover" />
              <div className="h-[280px] animate-pulse rounded bg-surface-hover" />
            </div>
          </CardContent>
        </Card>
        <Card variant="elevated" className="rounded-xl h-[340px] overflow-hidden">
          <CardContent className="p-5">
            <div className="space-y-3">
              <div className="h-5 w-28 animate-pulse rounded bg-surface-hover" />
              <div className="h-[280px] animate-pulse rounded bg-surface-hover" />
            </div>
          </CardContent>
        </Card>
      </div>
    </motion.div>
  );
}

/**
 * 角色页依赖完整 focus contract 才能解释“焦点人物”和“叙事中心度”；
 * 若 diagnosis 只有半成品焦点数据，就必须明确提示重跑，而不是继续渲染空焦点区
 */
function IncompleteFocusContractState() {
  return (
    <DashboardCardShell
      title="角色焦点结果需要重跑"
      icon={<AlertCircle className="h-4 w-4" />}
      accent="chart-5"
      className="min-h-[240px]"
      bodyClassName="items-center justify-center gap-3 text-center"
    >
      <p className="text-sm text-text-muted">
        当前任务缺少完整的焦点结构合同，请重新分析后再查看角色焦点结果。
      </p>
    </DashboardCardShell>
  );
}

/**
 * 角色页现在以 diagnosis 新合同为前置条件；
 * diagnosis 尚未产出时，不再提前渲染仅靠 annotation 聚合得到的角色表，
 * 避免页面继续对“无 diagnosis 的旧路径”做静默兼容
 */
function EmptyDiagnosisState() {
  return (
    <DashboardCardShell
      title="角色焦点结果暂未生成"
      icon={<Users className="h-4 w-4" />}
      accent="chart-2"
      className="min-h-[240px]"
      bodyClassName="items-center justify-center gap-3 text-center"
    >
      <p className="text-sm text-text-muted">当前任务暂时还没有可展示的角色焦点结果。</p>
    </DashboardCardShell>
  );
}

/* ------------------------------------------------------------------ */
/*  主组件                                                             */
/* ------------------------------------------------------------------ */

/**
 * 2026-04-27，任务：protagonist-focus-contract
 * 修改原因：角色页主展示逻辑改为消费 `focus_structure` / `focus_characters`，
 * 并用新的 FocusCastCard 与多焦点高亮替代旧单主角页面
 *
 * 2026-04-28，任务：分析详情页单屏 Tabs 改造
 * 修改原因：角色页主展示区拆成排行、功能焦点、角色表三个 tab，保证首屏优先展示排行
 */
export function CharactersPage() {
  const { novelId } = useParams<{ novelId: string }>();
  const [searchParams] = useSearchParams();
  const { currentTaskId, setNovel, setTask } = useNovelStore();

  const urlTaskId = searchParams.get("task_id");

  // 组件挂载时把 novelId 同步到 store；如果 URL 带 task_id 就一并初始化任务
  useEffect(() => {
    if (novelId) {
      setNovel(novelId);
      if (urlTaskId) {
        setTask(urlTaskId);
      }
    }
  }, [novelId, urlTaskId, setNovel, setTask]);

  // 数据获取
  const enabled = !!novelId && !!currentTaskId;

  const diagnosisQuery = useQuery({
    queryKey: ["results", novelId, currentTaskId, "diagnosis"],
    queryFn: () => getDiagnosis(novelId!, currentTaskId!),
    enabled,
    staleTime: STALE_TIME,
  });

  const diagnosis = diagnosisQuery.data;
  const hasFocusContract = hasCompleteFocusContract(diagnosis);
  const isDiagnosisRerunRequired =
    diagnosis?.rerun_required === true || (diagnosisQuery.isSuccess && diagnosis !== null && !hasFocusContract);
  const shouldFetchCharacters = enabled && diagnosisQuery.isSuccess && diagnosis !== null && !isDiagnosisRerunRequired;

  const charactersQuery = useQuery({
    queryKey: ["results", novelId, currentTaskId, "characters"],
    queryFn: () => getCharacters(novelId!, currentTaskId!),
    enabled: shouldFetchCharacters,
    staleTime: STALE_TIME,
  });

  const isLoading =
    enabled &&
    (diagnosisQuery.isLoading || (shouldFetchCharacters && charactersQuery.isLoading));
  const isAnalysisNotComplete =
    enabled &&
    (isAnalysisNotCompleteError(diagnosisQuery.error) ||
      (shouldFetchCharacters && isAnalysisNotCompleteError(charactersQuery.error)));
  const analysisFailed =
    enabled &&
    (getAnalysisNotCompleteRunStatus(diagnosisQuery.error) === "failed" ||
      (shouldFetchCharacters && getAnalysisNotCompleteRunStatus(charactersQuery.error) === "failed"));
  const isError =
    enabled &&
    (diagnosisQuery.isError || (shouldFetchCharacters && charactersQuery.isError)) &&
    !isAnalysisNotComplete;

  const retry = () => {
    if (shouldFetchCharacters) {
      charactersQuery.refetch();
    }
    diagnosisQuery.refetch();
  };

  const { data: characters } = charactersQuery;
  const focusCharacters = hasFocusContract ? diagnosis.focus_characters : [];
  const hasNullDiagnosis =
    enabled &&
    diagnosisQuery.isFetched &&
    !diagnosisQuery.isLoading &&
    !diagnosisQuery.isError &&
    diagnosis === null;
  const shouldShowIncompleteFocusContractState =
    diagnosisQuery.isSuccess &&
    diagnosis !== null &&
    !isLoading &&
    !isError &&
    isDiagnosisRerunRequired;

  // ---------- 渲染 ----------

  return (
    <AnalysisWorkspace title="角色分析">
      {/* 未选择任务提示 */}
      {!currentTaskId && (
        <DashboardCardShell
          title="角色分析"
          icon={<Users className="h-4 w-4" />}
          accent="chart-2"
          className="min-h-[240px]"
          bodyClassName="items-center justify-center gap-3 text-center"
        >
          <p className="text-sm text-text-muted">请先选择一个分析任务。</p>
        </DashboardCardShell>
      )}

      {/* 加载骨架屏 */}
      {isLoading && <SkeletonGrid />}

      {/* 错误状态 */}
      {isAnalysisNotComplete && !isLoading && (
        <AnalysisNotCompleteState
          title={analysisFailed ? "角色分析任务已失败" : "角色结果尚未完成"}
          description={
            analysisFailed
              ? "该分析任务已失败，角色焦点结果无法读取，请重新发起分析后再查看。"
              : "当前任务仍在分析中，角色焦点结果暂时不可读，请等待任务进入完成态后再查看。"
          }
          failed={analysisFailed}
        />
      )}
      {isError && !isLoading && (
        <DashboardCardShell
          title="角色数据加载失败"
          icon={<AlertCircle className="h-4 w-4" />}
          accent="chart-5"
          className="min-h-[240px]"
          bodyClassName="items-center justify-center gap-3 text-center"
        >
          <p className="text-sm text-text-muted">角色列表或诊断画像加载失败。</p>
          <Button variant="outline" size="sm" onClick={retry}>
            重试
          </Button>
        </DashboardCardShell>
      )}

      {/* 空数据状态 */}
      {characters && characters.length === 0 && !isLoading && !isError && (
        <DashboardCardShell
          title="暂无角色数据"
          icon={<Users className="h-4 w-4" />}
          accent="chart-4"
          className="min-h-[240px]"
          bodyClassName="items-center justify-center gap-3 text-center"
        >
          <p className="text-sm text-text-muted">当前任务尚未生成角色分析结果。</p>
        </DashboardCardShell>
      )}

      {/* diagnosis 为空时的状态 */}
      {hasNullDiagnosis && !isLoading && !isError && <EmptyDiagnosisState />}

      {/* 合同缺失状态 */}
      {shouldShowIncompleteFocusContractState && <IncompleteFocusContractState />}

      {/* 主内容 */}
      {characters && characters.length > 0 && !isLoading && !shouldShowIncompleteFocusContractState && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
          className="flex min-h-0 flex-1 flex-col"
        >
          {/*
            2026-04-28，任务：分析详情页单屏 Tabs 改造
            修改原因：角色页按“排行优先”拆成 tab，让排行、焦点和表格都接受同一单屏工作区边界。
          */}
          <AnalysisWorkspace.Tabs defaultValue="ranking">
            <AnalysisWorkspace.Tab value="ranking" label="角色排行">
              <CharacterRankingBar characters={characters} className="h-full" />
            </AnalysisWorkspace.Tab>
            <AnalysisWorkspace.Tab value="focus" label="功能与焦点">
              <div className="grid h-full min-h-0 grid-cols-1 gap-4 lg:grid-cols-2">
                <RoleFunctionPie characters={characters} className="h-full min-h-[320px]" />
                <FocusCastCard
                  characters={characters}
                  focusStructure={hasFocusContract ? diagnosis.focus_structure : undefined}
                  focusCharacters={focusCharacters}
                  arcScores={diagnosis?.arc_scores}
                  className="h-full min-h-[320px]"
                />
              </div>
            </AnalysisWorkspace.Tab>
            <AnalysisWorkspace.Tab value="table" label="角色表">
              <CharacterTable characters={characters} className="h-full" />
            </AnalysisWorkspace.Tab>
          </AnalysisWorkspace.Tabs>
        </motion.div>
      )}
    </AnalysisWorkspace>
  );
}
