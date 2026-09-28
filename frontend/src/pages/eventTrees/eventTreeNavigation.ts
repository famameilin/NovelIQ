/** 事件树深链同时保留任务、树和节点身份 */
export function buildEventTreeUrl(
  novelId: string,
  taskId: string,
  options: { treeId?: string | null; eventId?: string | null; chapterOrder?: number | null } = {},
): string {
  const params = new URLSearchParams({ task_id: taskId });
  if (options.treeId) params.set("tree_id", options.treeId);
  if (options.eventId) params.set("event_id", options.eventId);
  if (options.chapterOrder != null) params.set("chapter", String(options.chapterOrder));
  return `/novels/${novelId}/event-trees?${params.toString()}`;
}
