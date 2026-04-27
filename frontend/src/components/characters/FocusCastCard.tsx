import { useMemo } from "react";
import { Badge } from "@/components/ui/badge";
import { DashboardCardShell } from "@/components/common/DashboardCardShell";
import { Users, Star, Zap, Heart } from "lucide-react";
import { motion } from "framer-motion";
import { cn } from "@/lib/cn";
import type { Character, DiagnosisResult } from "@/api/types";

export interface FocusCastCardProps {
  /** 焦点结构 */
  focusStructure?: DiagnosisResult["focus_structure"];
  /** 焦点人物名称列表 */
  focusCharacters?: string[] | null;
  /** 角色列表 */
  characters: Character[];
  /** 弧线得分 */
  arcScores?: Record<string, number> | null;
  className?: string;
}

function getFocusStructureLabel(focusStructure?: DiagnosisResult["focus_structure"]): string {
  switch (focusStructure) {
    case "dual":
      return "双主角";
    case "ensemble":
      return "群像焦点";
    default:
      return "主角";
  }
}

/**
 * 2026-04-27，任务：protagonist-focus-contract
 * 新建原因：角色页不再展示“唯一主角卡”，而是统一展示焦点结构、焦点人物列表
 * 与叙事中心度最高角色，避免继续把“焦点身份”和“中心度分数”混成一个概念。
 */
export function FocusCastCard({
  focusStructure,
  focusCharacters,
  characters,
  arcScores,
  className,
}: FocusCastCardProps) {
  const focusNames = useMemo(() => focusCharacters ?? [], [focusCharacters]);
  const focusCharacterSet = useMemo(() => new Set(focusNames), [focusNames]);
  const focusLabel = getFocusStructureLabel(focusStructure);
  const topNarrativeCenterCharacter = useMemo(() => {
    return [...characters]
      .filter((character) => character.narrative_focus_score != null)
      .sort(
        (left, right) =>
          (right.narrative_focus_score ?? Number.NEGATIVE_INFINITY) -
          (left.narrative_focus_score ?? Number.NEGATIVE_INFINITY)
      )[0];
  }, [characters]);

  const hasData = focusNames.length > 0 || !!topNarrativeCenterCharacter;

  return (
    <DashboardCardShell
      title="焦点结构"
      icon={<Users className="h-4 w-4" />}
      accent="primary"
      showOrb
      className={cn(className)}
      bodyClassName="gap-4"
    >
      {hasData ? (
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35 }}
          className="flex flex-col gap-4"
        >
          <div className="rounded-2xl border border-border/60 bg-surface/70 p-4">
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold text-text">{focusLabel}</span>
              <Badge variant="secondary" className="text-[10px]">
                {focusStructure ?? "single"}
              </Badge>
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              {focusNames.length > 0 ? (
                focusNames.map((name) => (
                  <span
                    key={name}
                    className="rounded-full bg-primary/10 px-3 py-1.5 text-sm font-medium text-primary"
                  >
                    {name}
                  </span>
                ))
              ) : (
                <span className="text-sm text-text-muted">暂无焦点人物数据</span>
              )}
            </div>
          </div>

          <div className="grid grid-cols-3 gap-3">
            <div className="flex flex-col items-center rounded-xl border border-border/60 bg-surface/70 p-3">
              <Star className="mb-1 h-4 w-4 text-chart-1" />
              <span className="text-lg font-semibold text-text">{focusNames.length || "—"}</span>
              <span className="text-[10px] text-text-muted">焦点人数</span>
            </div>

            <div className="flex flex-col items-center rounded-xl border border-border/60 bg-surface/70 p-3">
              <Zap className="mb-1 h-4 w-4 text-chart-2" />
              <span className="text-lg font-semibold text-text">
                {topNarrativeCenterCharacter?.narrative_focus_score?.toFixed(2) ?? "—"}
              </span>
              <span className="text-[10px] text-text-muted">最高中心度</span>
            </div>

            <div className="flex flex-col items-center rounded-xl border border-border/60 bg-surface/70 p-3">
              <Heart className="mb-1 h-4 w-4 text-chart-3" />
              <span className="text-lg font-semibold text-text">
                {topNarrativeCenterCharacter?.avg_emotion_score != null
                  ? `${topNarrativeCenterCharacter.avg_emotion_score > 0 ? "+" : ""}${topNarrativeCenterCharacter.avg_emotion_score.toFixed(2)}`
                  : "—"}
              </span>
              <span className="text-[10px] text-text-muted">中心角色情绪均值</span>
            </div>
          </div>

          {topNarrativeCenterCharacter && (
            <div className="rounded-2xl border border-border/60 bg-surface/70 px-4 py-3">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="text-xs text-text-muted">叙事中心度最高角色</div>
                  <div className="text-sm font-semibold text-text">{topNarrativeCenterCharacter.name}</div>
                </div>
                {focusCharacterSet.has(topNarrativeCenterCharacter.name) && (
                  <Badge variant="secondary" className="text-[10px]">
                    焦点人物
                  </Badge>
                )}
              </div>
              {arcScores?.[topNarrativeCenterCharacter.name] != null && (
                <div className="mt-3 flex items-center gap-2">
                  <span className="text-xs text-text-muted">弧线得分:</span>
                  <span className="text-xs font-medium text-text">
                    {arcScores[topNarrativeCenterCharacter.name]}/10
                  </span>
                </div>
              )}
            </div>
          )}
        </motion.div>
      ) : (
        <div className="flex h-32 items-center justify-center text-sm text-text-muted">
          暂无焦点结构数据
        </div>
      )}
    </DashboardCardShell>
  );
}
