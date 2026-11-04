// 叙事页沿用 Tailwind 与主题变量，纸面和细线只限定在当前工作区
export const narrativePaper = "bg-background text-text";
export const narrativeMuted = "text-text-muted";
export const narrativeLine = "border-border";
export const control = "inline-flex min-h-9 max-w-full items-center justify-center gap-2 border-b border-border bg-transparent px-2 py-1.5 text-xs text-text-muted outline-none hover:bg-surface-hover focus-visible:ring-2 focus-visible:ring-primary/40 disabled:opacity-40 [&_option]:bg-surface [&_option]:text-text";
export const dimensionTones = {
  plot: "text-primary",
  character: "text-chart-5",
  relationship: "text-chart-3",
  foreshadowing: "text-chart-2",
};
export const dimensionLabels = { plot: "情节推进", character: "人物变化", relationship: "关系变化", foreshadowing: "伏笔动作" };
export const fieldLabels: Record<string, string> = { action: "行动", emotion: "情绪", role_function: "叙事作用", active: "关系有效", relation_type: "关系", change: "变化", reason: "依据" };
export function valueText(value: unknown, field?: string): string {
  if (value == null) return "此前未记录";
  if (field === "emotion") return ({ "-2": "强烈负面", "-1": "负面", "0": "平静", "1": "正面", "2": "强烈正面" } as Record<string, string>)[String(value)] ?? String(value);
  if (typeof value === "object") return Object.entries(value).map(([key, item]) => `${fieldLabels[key] ?? key}：${valueText(item, key)}`).join(" · ");
  if (typeof value === "boolean") return value ? "是" : "否";
  return String(value);
}

/** 图表色板循环，事件树不因颜色数量限制而截断 */
export function chartVar(index: number): string { return `--chart-${(index % 8) + 1}`; }

/** 事件树七色互不重复，同一棵树在点与线上使用同一色相 */
export function eventTreeColor(index: number): string {
  const slot = index % 7;
  const tone = `hsl(var(${chartVar([3, 4, 0, 1, 7, 5, 2][slot])}))`;
  if (slot === 0) return `hsl(from ${tone} calc(h + 6) calc(s + 25) calc(l - 7))`;
  if (slot === 1 || slot === 4) return `hsl(from ${tone} calc(h - 6) calc(s * .55) calc(l + 9))`;
  if (slot === 2) return `hsl(from ${tone} h calc(s * .9) calc(l + 8))`;
  if (slot === 3) return `hsl(from ${tone} calc(h - 15) calc(s * .69) calc(l + 9))`;
  if (slot === 5) return `hsl(from ${tone} calc(h + 6) calc(s + 15) calc(l + 7))`;
  return `hsl(from ${tone} calc(h + 15) s calc(l + 9))`;
}

export const eventTreeNeutral = "hsl(from hsl(var(--chart-neutral)) h calc(s * .4) calc(l + 24))";

const EVENT_LINE_TONES: Record<string, string> = {
  growth: "hsl(345 68% 58%)",
  family: "hsl(0 72% 56%)",
  court: "hsl(152 62% 40%)",
  military: "hsl(217 80% 55%)",
  academy: "hsl(187 62% 42%)",
  emotion: "hsl(262 72% 60%)",
  sect: "hsl(40 65% 47%)",
  jianghu: "hsl(215 16% 55%)",
  other: "hsl(220 10% 55%)",
};

/** 事件线按主题固定配色，同一主题在画布、图例和详情中保持一致 */
export function eventLineColor(id: string, colorIndex?: number): string {
  const theme = EVENT_LINE_TONES[id.split("-")[0]];
  if (theme) return theme;
  const keys = ["growth", "family", "court", "military", "jianghu", "emotion", "sect", "academy"];
  return colorIndex == null ? EVENT_LINE_TONES.other : EVENT_LINE_TONES[keys[colorIndex % keys.length]] ?? EVENT_LINE_TONES.other;
}
