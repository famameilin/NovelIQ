import { useMemo } from "react";
import { Users } from "lucide-react";

import type { Character, DiagnosisResult } from "@/api/types";
import { AnalysisDetails } from "@/components/common/AnalysisDetails";
import { AnalysisMetricStrip } from "@/components/common/AnalysisMetricStrip";
import { AnalysisViewSwitcher } from "@/components/common/AnalysisViewSwitcher";
import { DashboardCardShell } from "@/components/common/DashboardCardShell";
import { Badge } from "@/components/ui/badge";
import { formatAnalysisLabel } from "@/lib/analysisLabels";

interface CharacterLandscapeProps {
  characters: Character[];
  focusStructure?: DiagnosisResult["focus_structure"];
  focusCharacters: string[];
  arcScores?: Record<string, number> | null;
  view: "overview" | "ranking" | "detail";
  sortMode: CharacterSortMode;
  selectedName: string | null;
  onSortModeChange: (mode: CharacterSortMode) => void;
  onSelectName: (name: string) => void;
}

type CharacterSortMode = "appearance" | "focus";

const ROLE_SEGMENT_CLASSES = ["bg-primary", "bg-chart-2", "bg-chart-3", "bg-chart-4", "bg-chart-5"] as const;

/**
 * 2026-08-31，作用：格式化角色功能分布中的单项数值
 * 简要说明：总和接近一时按比例展示，否则保留原始计数口径
 */
function formatRoleDistributionValue(value: number, total: number): string {
  if (total > 0 && total <= 1.01) return `${(value * 100).toFixed(1)}%`;
  return Number.isInteger(value) ? String(value) : value.toFixed(2);
}

/**
 * 2026-08-31，作用：格式化角色平均情绪
 * 简要说明：正值补充加号，缺失值使用统一占位
 */
function formatEmotion(value: number | null | undefined): string {
  if (value == null) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}`;
}

/**
 * 2026-08-31，作用：渲染角色分析工作区的当前页签内容
 * 简要说明：概览、排行和详情共用页面级选择状态，避免在页签切换后丢失角色上下文
 */
export function CharacterLandscape({
  characters,
  focusStructure,
  focusCharacters,
  arcScores,
  view,
  sortMode,
  selectedName,
  onSortModeChange,
  onSelectName,
}: CharacterLandscapeProps) {
  const sortedCharacters = useMemo(
    () => [...characters].sort((left, right) => sortMode === "focus"
      ? (right.narrative_focus_score ?? -1) - (left.narrative_focus_score ?? -1)
      : right.appearance_count - left.appearance_count),
    [characters, sortMode],
  );
  const selectedCharacter = characters.find((character) => character.name === selectedName) ?? sortedCharacters[0] ?? null;
  const topAppearanceCharacter = [...characters].sort((left, right) => right.appearance_count - left.appearance_count)[0];
  const topNarrativeCharacter = [...characters].sort(
    (left, right) => (right.narrative_focus_score ?? -1) - (left.narrative_focus_score ?? -1),
  )[0];
  const maxAppearance = topAppearanceCharacter?.appearance_count ?? 0;
  const roleComposition = useMemo(() => {
    const counts = new Map<string, number>();
    characters.forEach((character) => {
      const role = character.dominant_role_function?.trim();
      if (role) counts.set(role, (counts.get(role) ?? 0) + 1);
    });
    return [...counts.entries()].sort((left, right) => right[1] - left[1]);
  }, [characters]);
  const selectedDistribution = Object.entries(selectedCharacter?.role_function_distribution ?? {}).sort(
    (left, right) => right[1] - left[1],
  );
  const selectedDistributionTotal = selectedDistribution.reduce((sum, [, value]) => sum + value, 0);

  if (view === "overview") {
    return (
      <DashboardCardShell
        title="角色格局"
        icon={<Users className="h-4 w-4" aria-hidden="true" />}
        accent="primary"
        className="h-full"
        contentClassName="flex h-full flex-col"
        bodyClassName="min-h-0 flex-1 gap-5 overflow-y-auto pr-1"
      >
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="secondary">{formatAnalysisLabel(focusStructure, "focus")}</Badge>
        {focusCharacters.map((name) => <Badge key={name} variant="outline">{name}</Badge>)}
      </div>

      <AnalysisMetricStrip items={[
        { label: "识别角色", value: characters.length },
        { label: "焦点人物", value: focusCharacters.length },
        { label: "最高出场", value: topAppearanceCharacter ? `${topAppearanceCharacter.appearance_count} 次` : "—", description: topAppearanceCharacter?.name },
        { label: "叙事中心", value: topNarrativeCharacter?.name ?? "—", description: topNarrativeCharacter?.narrative_focus_score?.toFixed(2) },
      ]} />

      <section aria-labelledby="character-role-composition">
        <div className="flex items-center justify-between gap-3">
          <h2 id="character-role-composition" className="text-sm font-medium text-text">角色功能构成</h2>
          <span className="text-xs text-text-muted">按主导职责统计</span>
        </div>
        {roleComposition.length > 0 ? (
          <>
            <div className="mt-3 flex h-3 overflow-hidden rounded-full bg-surface-hover" aria-label="角色功能构成比例">
              {roleComposition.map(([role, count], index) => (
                <span key={role} className={ROLE_SEGMENT_CLASSES[index % ROLE_SEGMENT_CLASSES.length]} style={{ width: `${count / characters.length * 100}%` }} title={`${formatAnalysisLabel(role, "role")} ${(count / characters.length * 100).toFixed(1)}%`} />
              ))}
            </div>
            <div className="mt-3 flex flex-wrap gap-x-4 gap-y-2">
              {roleComposition.map(([role, count], index) => (
                <span key={role} className="flex items-center gap-1.5 text-xs text-text-muted">
                  <span className={`h-2 w-2 rounded-full ${ROLE_SEGMENT_CLASSES[index % ROLE_SEGMENT_CLASSES.length]}`} />
                  {formatAnalysisLabel(role, "role")} {((count / characters.length) * 100).toFixed(1)}%
                </span>
              ))}
            </div>
          </>
        ) : <p className="mt-3 text-sm text-text-muted">暂无角色功能构成</p>}
      </section>
      </DashboardCardShell>
    );
  }

  if (view === "ranking") {
    return (
      <DashboardCardShell
        title="综合角色榜"
        icon={<Users className="h-4 w-4" aria-hidden="true" />}
        accent="chart-2"
        className="h-full"
        contentClassName="flex h-full flex-col"
        bodyClassName="min-h-0 flex-1 gap-3 overflow-hidden"
      >
      <section className="flex min-h-0 flex-1 flex-col" aria-labelledby="character-ranking-title">
        <div className="flex items-center justify-between gap-3">
          <h2 id="character-ranking-title" className="text-sm font-medium text-text">综合角色榜</h2>
          <AnalysisViewSwitcher value={sortMode} onValueChange={onSortModeChange} label="角色排序方式" options={[
            { value: "appearance", label: "按出场" },
            { value: "focus", label: "按焦点" },
          ]} />
        </div>
        <div className="mt-3 flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg border border-border/70">
          <div className="shrink-0">
            <div className="grid grid-cols-[minmax(150px,1fr)_minmax(190px,1.35fr)_minmax(110px,.8fr)_80px_80px_70px] gap-3 bg-surface-hover/70 px-4 py-2 text-xs text-text-muted">
              <span>角色</span><span>出场强度</span><span>叙事职责</span><span>焦点</span><span>情绪</span><span>弧线</span>
            </div>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto" aria-label="角色排行列表">
            {sortedCharacters.map((character, index) => {
              const isSelected = selectedCharacter?.name === character.name;
              return (
                <button key={character.name} type="button" aria-pressed={isSelected} onClick={() => onSelectName(character.name)} className={`grid w-full grid-cols-[minmax(150px,1fr)_minmax(190px,1.35fr)_minmax(110px,.8fr)_80px_80px_70px] items-center gap-3 border-t border-border/55 px-4 py-3 text-left text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary/45 ${isSelected ? "bg-primary/5" : "bg-surface/55 hover:bg-surface-hover"}`}>
                  <span className="flex min-w-0 items-center gap-2 font-medium text-text">
                    <span className="w-5 shrink-0 text-xs tabular-nums text-text-muted">{index + 1}</span><span className="truncate">{character.name}</span>
                    {character.is_focus_character ? <Badge variant="secondary">焦点</Badge> : null}
                  </span>
                  <span className="flex items-center gap-3">
                    <span className="h-2 min-w-0 flex-1 overflow-hidden rounded-full bg-surface-hover"><span className="block h-full rounded-full bg-primary" style={{ width: `${maxAppearance > 0 ? character.appearance_count / maxAppearance * 100 : 0}%` }} /></span>
                    <span className="w-10 text-right tabular-nums text-text-muted">{character.appearance_count}</span>
                  </span>
                  <span className="truncate text-text">{formatAnalysisLabel(character.dominant_role_function, "role")}</span>
                  <span className="tabular-nums text-text">{character.narrative_focus_score?.toFixed(2) ?? "—"}</span>
                  <span className="tabular-nums text-text">{formatEmotion(character.avg_emotion_score)}</span>
                  <span className="tabular-nums text-text">{arcScores?.[character.name]?.toFixed(1) ?? "—"}</span>
                </button>
              );
            })}
          </div>
        </div>
      </section>
      </DashboardCardShell>
    );
  }

  return (
    <DashboardCardShell
      title="角色详情"
      icon={<Users className="h-4 w-4" aria-hidden="true" />}
      accent="chart-3"
      className="h-full"
      contentClassName="flex h-full flex-col"
      bodyClassName="min-h-0 flex-1 overflow-y-auto pr-1"
    >
      {selectedCharacter ? (
        <section className="rounded-lg border border-primary/20 bg-primary/5 p-4" aria-label={`${selectedCharacter.name}角色详情`}>
          <div className="flex items-center justify-between gap-3">
            <div><h2 className="font-semibold text-text">{selectedCharacter.name}</h2><p className="mt-1 text-sm text-text-muted">{formatAnalysisLabel(selectedCharacter.dominant_role_function, "role")} · 出场 {selectedCharacter.appearance_count} 次</p></div>
            <div className="flex flex-wrap gap-2">
              <Badge variant="secondary">焦点 {selectedCharacter.narrative_focus_score?.toFixed(2) ?? "—"}</Badge>
              <Badge variant="outline">情绪 {formatEmotion(selectedCharacter.avg_emotion_score)}</Badge>
              <Badge variant="outline">人物弧线 {arcScores?.[selectedCharacter.name]?.toFixed(1) ?? "—"}</Badge>
            </div>
          </div>
          <AnalysisDetails className="mt-4" description="主导占比与完整角色功能分布">
            <dl className="grid grid-cols-2 gap-4 text-sm">
              <div><dt className="text-text-muted">主导职责占比</dt><dd className="mt-1 font-medium text-text">{selectedCharacter.dominant_role_ratio != null ? `${(selectedCharacter.dominant_role_ratio * 100).toFixed(1)}%` : "—"}</dd></div>
              <div>
                <dt className="text-text-muted">完整功能构成</dt>
                <dd className="mt-1 flex flex-wrap gap-2">
                  {selectedDistribution.length > 0 ? selectedDistribution.map(([role, value]) => (
                    <span key={role} className="rounded-md border border-border/60 bg-surface/70 px-2 py-1">{formatAnalysisLabel(role, "role")} {formatRoleDistributionValue(value, selectedDistributionTotal)}</span>
                  )) : "—"}
                </dd>
              </div>
            </dl>
          </AnalysisDetails>
        </section>
      ) : <p className="text-sm text-text-muted">暂无可查看的角色详情</p>}
    </DashboardCardShell>
  );
}
