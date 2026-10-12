// 2026-04-23，任务：复杂度与耦合审查 P1
// 集中管理图谱页和时间轴页的深链 URL 构造，避免页面与 hook 各自拼接参数

export function buildGraphUrl(
  novelId: string,
  taskId: string,
  options?: { chapterId?: number | null; changeId?: string | null }
): string {
  const params = new URLSearchParams({ task_id: taskId });
  if (options?.chapterId != null) {
    params.set("selected_chapter", String(options.chapterId));
  }
  if (options?.changeId) {
    params.set("change_id", options.changeId);
  }
  return `/novels/${novelId}/graph?${params.toString()}`;
}

/** 图谱仅传真实来源事实，由时间轴查询映射独立变化身份 */
export function buildTimelineUrl(novelId: string, taskId: string): string {
  return `/novels/${novelId}/timeline?task_id=${taskId}`;
}
export function buildTimelineSelectionUrl(baseUrl: string, options?: { chapterId?: number | null; sourceFactId?: string | null }): string {
  const [path, query] = baseUrl.split("?");
  const params = new URLSearchParams(query);
  if (options?.chapterId != null) params.set("through_chapter_id", String(options.chapterId));
  if (options?.sourceFactId) params.set("source_fact_id", options.sourceFactId);
  return `${path}?${params}`;
}
