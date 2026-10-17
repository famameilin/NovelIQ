/** 用正式事件身份打开事件树，时间线自身阅读状态保持独立 */
export function buildEventTreeUrl(
  novelId: string,
  taskId: string,
  options: { eventId?: string | null } = {},
): string {
  const params = new URLSearchParams({ task_id: taskId });
  if (options.eventId) params.set("event_id", options.eventId);
  return `/novels/${novelId}/event-trees?${params.toString()}`;
}
