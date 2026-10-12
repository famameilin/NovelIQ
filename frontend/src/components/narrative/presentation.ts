// 叙事页沿用 Tailwind 与主题变量，纸面和细线只限定在当前工作区
export const narrativePaper = "bg-background text-text";
export const narrativeMuted = "text-text-muted";
export const narrativeLine = "border-border";
export const narrativeHeader = "mb-0 border-b border-border py-5 [&_h1]:relative [&_h1]:text-2xl [&_h1]:font-medium [&_h1]:text-inherit [&_h1]:after:absolute [&_h1]:after:-bottom-[21px] [&_h1]:after:left-0 [&_h1]:after:h-[3px] [&_h1]:after:w-full [&_h1]:after:bg-primary";
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
