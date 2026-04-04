import type {
  NarrativeStructureMetrics,
  EmotionStatsMetrics,
  CharacterStatsMetrics,
  StyleStatsMetrics,
  CultureStatsMetrics,
} from "@/api/types";

/* ------------------------------------------------------------------ */
/*  Types                                                             */
/* ------------------------------------------------------------------ */

export interface RadarDimension {
  name: string;
  value: number;
}

export interface AllMetrics {
  narrative: NarrativeStructureMetrics;
  emotion: EmotionStatsMetrics;
  character: CharacterStatsMetrics;
  style: StyleStatsMetrics;
  culture: CultureStatsMetrics;
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                           */
/* ------------------------------------------------------------------ */

function clamp(v: number, lo = 0, hi = 100): number {
  return Math.max(lo, Math.min(hi, v));
}

/* ------------------------------------------------------------------ */
/*  Per-dimension normalization (0–100)                                */
/* ------------------------------------------------------------------ */

export function normalizeNarrative(m: NarrativeStructureMetrics): number {
  // cliffhanger_rate: ideal ~0.3-0.6, higher is better for serialization
  const cliffScore = clamp((m.cliffhanger_rate - 0.1) * 200);
  // middle_collapse_index: ideal >= 0.85, > 1.0 means strong middle
  const midScore = clamp((m.middle_collapse_index - 0.5) * 100);
  return Math.round(clamp((cliffScore * 0.5 + midScore * 0.5)));
}

export function normalizeEmotion(m: EmotionStatsMetrics): number {
  // pivot_moment_density: more turning points = richer emotional landscape
  const pivotScore = clamp(m.pivot_moment_density * 300);
  // recovery_speed: higher = more resilient emotional arcs
  const recoveryScore = clamp(m.recovery_speed * 100);
  return Math.round(clamp((pivotScore * 0.6 + recoveryScore * 0.4)));
}

export function normalizeCharacter(m: CharacterStatsMetrics): number {
  // network_density: 0-1 range, 0.3-0.5 is healthy
  const densityScore = clamp(m.network_density * 150);
  // greimas_coverage: 0-1 range, higher = more complete role coverage
  const greimasScore = clamp(m.greimas_coverage * 100);
  return Math.round(clamp((densityScore * 0.5 + greimasScore * 0.5)));
}

export function normalizeStyle(m: StyleStatsMetrics): number {
  // vocab_breadth: typically 0-1, higher = richer vocabulary
  const vocabScore = clamp(m.vocab_breadth * 100);
  // dialogue_ratio: 0-1, moderate is ideal (~0.4)
  const dialogueScore = clamp(100 - Math.abs(m.dialogue_ratio - 0.4) * 150);
  return Math.round(clamp((vocabScore * 0.7 + dialogueScore * 0.3)));
}

export function normalizeCulture(m: CultureStatsMetrics): number {
  // idiom_density: typically small, scale up
  const idiomScore = clamp(m.idiom_density * 300);
  // imagery_density: typically small
  const imageryScore = clamp(m.imagery_density * 300);
  // classical_sentence_ratio: typically small
  const classicalScore = clamp(m.classical_sentence_ratio * 200);
  return Math.round(clamp((idiomScore * 0.4 + imageryScore * 0.35 + classicalScore * 0.25)));
}

/* ------------------------------------------------------------------ */
/*  Aggregate into radar dimensions                                    */
/* ------------------------------------------------------------------ */

export function toRadarDimensions(metrics: AllMetrics): RadarDimension[] {
  return [
    { name: "叙事结构", value: normalizeNarrative(metrics.narrative) },
    { name: "情感统计", value: normalizeEmotion(metrics.emotion) },
    { name: "人物网络", value: normalizeCharacter(metrics.character) },
    { name: "风格指标", value: normalizeStyle(metrics.style) },
    { name: "文化元素", value: normalizeCulture(metrics.culture) },
  ];
}
