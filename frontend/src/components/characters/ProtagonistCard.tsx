import { FocusCastCard } from "@/components/characters/FocusCastCard";
import type { Character } from "@/api/types";

export interface ProtagonistCardProps {
  /** 旧调用方透传的单角色对象 */
  protagonist?: Character | null;
  /** 旧调用方透传的备用角色名 */
  protagonistName?: string | null;
  /** 旧调用方透传的弧线得分 */
  arcScores?: Record<string, number> | null;
  className?: string;
}

/**
 * 2026-04-27，任务：protagonist-focus-contract
 * 修改原因：保留旧文件路径，避免项目中其他演示页或临时引用直接失效；
 * 但内部实现已完全切到新的 FocusCastCard，不再直接消费旧主角分字段。
 */
export function ProtagonistCard({
  protagonist,
  protagonistName,
  arcScores,
  className,
}: ProtagonistCardProps) {
  const fallbackName = protagonist?.name ?? protagonistName ?? null;
  const fallbackCharacter =
    protagonist ??
    (fallbackName
      ? {
          name: fallbackName,
          appearance_count: 0,
          dominant_role_function: "",
          role_function_distribution: {},
          dominant_role_ratio: 0,
          narrative_focus_score: 0,
          is_focus_character: true,
          avg_emotion_score: null,
        }
      : null)
  return (
    <FocusCastCard
      characters={fallbackCharacter ? [fallbackCharacter] : []}
      focusStructure="single"
      focusCharacters={fallbackName ? [fallbackName] : []}
      arcScores={arcScores}
      className={className}
    />
  );
}
