// 2026-04-23，任务：复杂度与耦合审查 P1
// 集中管理图谱页和时间轴页的深链 URL 构造，避免页面与 hook 各自拼接参数

export function buildGraphUrl(
  novelId: string,
  taskId: string,
  options?: { chunkId?: number | null; changeId?: string | null }
): string {
  const params = new URLSearchParams({ task_id: taskId });
  if (options?.chunkId != null) {
    params.set("selected_chunk", String(options.chunkId));
  }
  if (options?.changeId) {
    params.set("change_id", options.changeId);
  }
  return `/novels/${novelId}/graph?${params.toString()}`;
}

// 2026-04-23，任务：复杂度与耦合审查 P1
// 统一时间轴入口 URL，确保图谱页各跳转点保持同一默认参数口径
//

// - 时间轴默认入口改为 `view=composite`
// - 移除未消费的 `show_tension` 参数，避免 URL 语义继续漂移
export function buildTimelineUrl(novelId: string, taskId: string): string {
  return `/novels/${novelId}/timeline?task_id=${taskId}&max_level=3&view=composite`;
}

// 2026-04-23，任务：复杂度与耦合审查 P1
// 把时间轴联动参数拼装从页面组件中抽出，减少 UI 代码中的字符串拼接
export function buildTimelineSelectionUrl(
  baseUrl: string,
  options?: { selectedNodeId?: string | null; chunkId?: number | null; changeId?: string | null }
): string {
  const params: string[] = [];
  if (options?.selectedNodeId) {
    params.push(`selected_node_id=${encodeURIComponent(options.selectedNodeId)}`);
  }
  if (options?.chunkId != null) {
    params.push(`selected_chunk=${options.chunkId}`);
  }
  if (options?.changeId) {
    params.push(`change_id=${encodeURIComponent(options.changeId)}`);
  }
  if (params.length === 0) {
    return baseUrl;
  }
  return `${baseUrl}&${params.join("&")}`;
}
