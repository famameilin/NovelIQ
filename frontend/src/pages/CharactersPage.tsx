import { useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { isAnalysisNotCompleteError, getAnalysisNotCompleteRunStatus } from "@/api/errorGuards";
import { getCharacters } from "@/api/results";
import { getCharacterFunctionTab, tabQueryKey } from "@/api/tabs";
import { useNovelScopedTask } from "@/hooks/useNovelScopedTask";
import { AnalysisNotCompleteState } from "@/components/common/AnalysisNotCompleteState";
import { AnalysisWorkspace } from "@/components/layout/AnalysisWorkspace";
import { DashboardCardShell } from "@/components/common/DashboardCardShell";
import { CharacterLandscape } from "@/components/characters/CharacterLandscape";
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
      <div className="grid grid-cols-2 gap-6">
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

/* ------------------------------------------------------------------ */
/*  主组件                                                             */
/* ------------------------------------------------------------------ */

/**
 * 2026-04-27，作用：展示角色格局分析页面
 * 简要说明：消费角色列表与焦点结构，在单一文档流中整合排行、功能分布和角色详情
 */
export function CharactersPage() {
  const { novelId } = useParams<{ novelId: string }>();
  const [searchParams] = useSearchParams();

  const urlTaskId = searchParams.get("task_id");

  // 2026-08-13 P1-2: 小说作用域任务守卫——跨小说切换后旧小说的任务
  // 不得用于新小说的查询/SSE（模式同 GraphPage）
  const { storeTaskId } = useNovelScopedTask(novelId, urlTaskId);

  // 角色基础指标和焦点结构分别使用各自的聚合数据源
  const enabled = !!novelId && !!storeTaskId;

  const charactersQuery = useQuery({
    queryKey: ["characters", novelId, storeTaskId],
    queryFn: () => getCharacters(novelId!, storeTaskId!),
    enabled,
    staleTime: STALE_TIME,
  });

  const focusQuery = useQuery({
    queryKey: tabQueryKey("character-function", novelId, storeTaskId),
    queryFn: () => getCharacterFunctionTab(novelId!, storeTaskId!),
    enabled,
    staleTime: STALE_TIME,
  });

  const isLoading = enabled && (charactersQuery.isLoading || focusQuery.isLoading);
  const isAnalysisNotComplete =
    enabled && (isAnalysisNotCompleteError(charactersQuery.error) || isAnalysisNotCompleteError(focusQuery.error));
  const analysisFailed =
    enabled &&
    (getAnalysisNotCompleteRunStatus(charactersQuery.error) === "failed" ||
      getAnalysisNotCompleteRunStatus(focusQuery.error) === "failed");
  const isError = enabled && (charactersQuery.isError || focusQuery.isError) && !isAnalysisNotComplete;

  const retry = () => {
    charactersQuery.refetch();
    focusQuery.refetch();
  };

  const { data: characters } = charactersQuery;
  const focusData = focusQuery.data;
  const focusCharacters = focusData?.focus_characters ?? [];
  const [sortMode, setSortMode] = useState<"appearance" | "focus">("appearance");
  const [selectedName, setSelectedName] = useState<string | null>(null);
  // ---------- 渲染 ----------

  return (
    <AnalysisWorkspace title="角色格局">
      {/* 未选择任务提示 */}
      {!storeTaskId && (
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

      {/* 主内容 */}
      {characters && characters.length > 0 && !isLoading && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
          className="flex h-full min-h-0 flex-col"
        >
          <AnalysisWorkspace.Tabs defaultValue="overview">
            <AnalysisWorkspace.Tab value="overview" label="格局概览">
              <CharacterLandscape
                characters={characters}
                focusStructure={focusData?.focus_structure}
                focusCharacters={focusCharacters}
                arcScores={focusData?.arc_scores}
                view="overview"
                sortMode={sortMode}
                selectedName={selectedName}
                onSortModeChange={setSortMode}
                onSelectName={setSelectedName}
              />
            </AnalysisWorkspace.Tab>
            <AnalysisWorkspace.Tab value="ranking" label="角色排行">
              <CharacterLandscape
                characters={characters}
                focusStructure={focusData?.focus_structure}
                focusCharacters={focusCharacters}
                arcScores={focusData?.arc_scores}
                view="ranking"
                sortMode={sortMode}
                selectedName={selectedName}
                onSortModeChange={setSortMode}
                onSelectName={setSelectedName}
              />
            </AnalysisWorkspace.Tab>
            <AnalysisWorkspace.Tab value="detail" label="角色详情">
              <CharacterLandscape
                characters={characters}
                focusStructure={focusData?.focus_structure}
                focusCharacters={focusCharacters}
                arcScores={focusData?.arc_scores}
                view="detail"
                sortMode={sortMode}
                selectedName={selectedName}
                onSortModeChange={setSortMode}
                onSelectName={setSelectedName}
              />
            </AnalysisWorkspace.Tab>
          </AnalysisWorkspace.Tabs>
        </motion.div>
      )}
    </AnalysisWorkspace>
  );
}
