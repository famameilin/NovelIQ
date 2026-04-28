import type { DiagnosisResult } from "@/api/types";

/**
 * 前端多个页面都需要判断 diagnosis 是否具备完整的焦点合同；
 * 如果只拿到了 ledger-only、缺 focus 字段，或缺主题命名的半成品结果，页面必须显式提示重跑，
 * 不能再静默降级成“正常页面但焦点区为空”。
 */
export function hasCompleteFocusContract(
  diagnosis: DiagnosisResult | null | undefined,
): diagnosis is DiagnosisResult & {
  arc_scores: Record<string, number>;
  focus_structure: "single" | "dual" | "ensemble";
  focus_characters: string[];
  main_characters: string[];
  core_cast: string[];
} {
  if (diagnosis?.rerun_required) {
    return false;
  }
  if (
    !diagnosis?.focus_structure ||
    !diagnosis.arc_scores ||
    Object.keys(diagnosis.arc_scores).length === 0 ||
    !Array.isArray(diagnosis.focus_characters) ||
    !Array.isArray(diagnosis.topic_labels) ||
    !Array.isArray(diagnosis.main_characters) ||
    !Array.isArray(diagnosis.core_cast) ||
    diagnosis.topic_labels.length === 0 ||
    diagnosis.main_characters.length === 0 ||
    diagnosis.core_cast.length === 0
  ) {
    return false;
  }

  const normalizedFocusCharacters = diagnosis.focus_characters
    .map((name) => name.trim())
    .filter((name) => name.length > 0);

  if (normalizedFocusCharacters.length !== diagnosis.focus_characters.length) {
    return false;
  }

  switch (diagnosis.focus_structure) {
    case "single":
      return normalizedFocusCharacters.length === 1;
    case "dual":
      return normalizedFocusCharacters.length === 2;
    case "ensemble":
      return normalizedFocusCharacters.length >= 3;
    default:
      return false;
  }
}
