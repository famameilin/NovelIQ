import { apiClient } from "./client";
import type {
  DiagnosisResult,
  ForeshadowingTree,
  GraphChangesPageResponse,
  EventForestResponse,
  EventSourceChapterResponse,
  EmotionTrendWindow,
  TopicEmotionResponse,
  TopicSeriesResponse,
  TopicShiftResponse,
} from "./types";
import type { NarrativeTreeDetail, NarrativeTreeResponse, NarrativeSource, ProgressionChange, ProgressionDimension, ProgressionTimelineResponse } from "./narrativeTypes";

// 情绪趋势窗口聚合：window_paragraphs 作用于 range 区间内（缺省=全书）；
// 情绪趋势 tab 的数据源（单源端点直接作为 tab API）
export async function getEmotionTrend(
  novelId: string,
  taskId: string,
  options?: { range?: [number, number]; windowParagraphs?: number }
): Promise<EmotionTrendWindow[]> {
  const { data } = await apiClient.get<EmotionTrendWindow[]>(
    `/api/novels/${novelId}/emotion-trend`,
    {
      params: {
        task_id: taskId,
        ...(options?.range && { range: options.range.join(",") }),
        ...(options?.windowParagraphs != null && { window_paragraphs: options.windowParagraphs }),
      },
    }
  );
  return data;
}

// 诊断报告：诊断摘要/价值与主题 tab 的数据源（展示主体原样透传）
export async function getDiagnosis(
  novelId: string,
  taskId: string
): Promise<DiagnosisResult> {
  const { data } = await apiClient.get<DiagnosisResult>(
    `/api/novels/${novelId}/diagnosis`,
    { params: { task_id: taskId } }
  );
  return data;
}

// 伏笔树：跨章节伏笔状态的数据源（展示主体原样透传）
export async function getForeshadowingTrees(
  novelId: string,
  taskId: string
): Promise<ForeshadowingTree[]> {
  const { data } = await apiClient.get<ForeshadowingTree[]>(
    `/api/novels/${novelId}/foreshadowing-trees`,
    { params: { task_id: taskId } }
  );
  return data;
}

// 按章节倒序获取实体状态与关系变化：图谱变化 tab 的数据源
export async function getGraphChanges(
  novelId: string,
  taskId: string,
  options?: { chapterId?: number; changesCursor?: string | null; changesLimit?: number }
): Promise<GraphChangesPageResponse> {
  const { data } = await apiClient.get<GraphChangesPageResponse>(
    `/api/novels/${novelId}/graph/changes`,
    {
      params: {
        task_id: taskId,
        ...(options?.chapterId != null ? { chapter_id: options.chapterId } : {}),
        ...(options?.changesCursor ? { changes_cursor: options.changesCursor } : {}),
        ...(options?.changesLimit != null && { changes_limit: options.changesLimit }),
      },
    }
  );
  return data;
}

/** 截点约束所有事实；窗口仅控制显示范围，状态由服务端完整归并 */
export async function getTimeline(
  novelId: string,
  taskId: string,
  options: { throughChapterId?: number; windowStartChapterId?: number; windowEndChapterId?: number; subjectId?: string; dimension?: ProgressionDimension; q?: string; cursor?: string; limit?: number; sourceFactId?: string; signal?: AbortSignal } = {},
): Promise<ProgressionTimelineResponse> {
  const { signal, ...query } = options;
  const { data } = await apiClient.get<ProgressionTimelineResponse>(
    `/api/novels/${novelId}/timeline`,
    {
      params: {
        task_id: taskId,
        ...definedParams({ through_chapter_id: query.throughChapterId, window_start_chapter_id: query.windowStartChapterId, window_end_chapter_id: query.windowEndChapterId, subject_id: query.subjectId, dimension: query.dimension, q: query.q, cursor: query.cursor, limit: query.limit, source_fact_id: query.sourceFactId }),
      },
      signal,
    }
  );
  return data;
}

function definedParams(values: Record<string, unknown>) {
  return Object.fromEntries(Object.entries(values).filter(([, value]) => value !== undefined));
}

/** 分支分页和全书搜索使用同一任务身份，原文请求不复用另一页上下文 */
export async function getEventTrees(novelId: string, taskId: string, options: { parentId?: string; q?: string; chapterId?: number; cursor?: string; limit?: number; expandAll?: boolean; signal?: AbortSignal } = {}): Promise<NarrativeTreeResponse> {
  const { data } = await apiClient.get<NarrativeTreeResponse>(`/api/novels/${novelId}/event-trees`, { params: { task_id: taskId, ...definedParams({ parent_id: options.parentId, q: options.q, chapter_id: options.chapterId, cursor: options.cursor, limit: options.limit, expand_all: options.expandAll }) }, signal: options.signal });
  return data;
}

/** 默认展开全书，自动消费分页，不能把每个分支的第一页当成完整事件树 */
export async function getEventTreeBook(novelId: string, taskId: string, signal?: AbortSignal): Promise<NarrativeTreeResponse> {
  const first = await getEventTrees(novelId, taskId, { limit: 500, expandAll: true, signal });
  const nodes = new Map(first.nodes.map(node => [node.node_id, node]));
  const edgeKey = (edge: NarrativeTreeResponse["edges"][number]) => `${edge.source_id}:${edge.target_id}:${edge.kind}`;
  const edges = new Map(first.edges.map(edge => [edgeKey(edge), edge]));
  let cursor = first.next_cursor;
  while (cursor) {
    const page = await getEventTrees(novelId, taskId, { limit: 500, expandAll: true, cursor, signal });
    page.nodes.forEach(node => nodes.set(node.node_id, node));
    page.edges.forEach(edge => edges.set(edgeKey(edge), edge));
    cursor = page.next_cursor;
  }
  return { ...first, nodes: [...nodes.values()], edges: [...edges.values()], next_cursor: null };
}

export async function getEventTreeNode(novelId: string, taskId: string, nodeId: string, signal?: AbortSignal): Promise<NarrativeTreeDetail> {
  const { data } = await apiClient.get<NarrativeTreeDetail>(`/api/novels/${novelId}/event-trees/nodes/${encodeURIComponent(nodeId)}`, { params: { task_id: taskId }, signal });
  return data;
}

export async function getTimelineChange(novelId: string, taskId: string, changeId: string, throughChapterId: number, signal?: AbortSignal): Promise<ProgressionChange> {
  const { data } = await apiClient.get<ProgressionChange>(`/api/novels/${novelId}/timeline/changes/${encodeURIComponent(changeId)}`, { params: { task_id: taskId, through_chapter_id: throughChapterId }, signal });
  return data;
}

export async function getNarrativeSource(novelId: string, taskId: string, context: { page: "timeline" | "event-trees"; id: string; chapterId?: number; throughChapterId?: number }, signal?: AbortSignal): Promise<NarrativeSource> {
  const resource = context.page === "timeline" ? "changes" : "nodes";
  const { data } = await apiClient.get<NarrativeSource>(`/api/novels/${novelId}/${context.page}/${resource}/${encodeURIComponent(context.id)}/source`, { params: { task_id: taskId, ...definedParams({ chapter_id: context.chapterId, through_chapter_id: context.throughChapterId }) }, signal });
  return data;
}

/** 事件树页按任务读取一份完整森林快照，章节筛选在前端进行 */
export async function getEventForest(novelId: string, taskId: string): Promise<EventForestResponse> {
  const { data } = await apiClient.get<EventForestResponse>(`/api/novels/${novelId}/event-forest`, {
    params: { task_id: taskId },
  });
  return data;
}

/** 仅在读者打开原文时读取当前事件所在章节 */
export async function getEventSourceChapter(
  novelId: string,
  taskId: string,
  chapterId: number,
): Promise<EventSourceChapterResponse> {
  const { data } = await apiClient.get<EventSourceChapterResponse>(
    `/api/novels/${novelId}/event-forest/chapters/${chapterId}/source`,
    { params: { task_id: taskId } },
  );
  return data;
}

// 主题演进 tab 数据源：段落完整 K 维权重，横轴真实字符位置（echarts sampling 降采样在前端）
export async function getTopicSeries(
  novelId: string,
  taskId: string
): Promise<TopicSeriesResponse> {
  const { data } = await apiClient.get<TopicSeriesResponse>(
    `/api/novels/${novelId}/topics/series`,
    { params: { task_id: taskId } }
  );
  return data;
}

// 主题迁移 tab 数据源：相邻窗口分布的 JS 散度候选点（参数为版本化配置的显式覆盖）
export async function getTopicShifts(
  novelId: string,
  taskId: string,
  options?: {
    windowSize?: number;
    minTokensPerWindow?: number;
    scoreThreshold?: number;
    maxCandidates?: number;
  }
): Promise<TopicShiftResponse> {
  const { data } = await apiClient.get<TopicShiftResponse>(
    `/api/novels/${novelId}/topics/shifts`,
    {
      params: {
        task_id: taskId,
        ...(options?.windowSize != null && { window_size: options.windowSize }),
        ...(options?.minTokensPerWindow != null && { min_tokens_per_window: options.minTokensPerWindow }),
        ...(options?.scoreThreshold != null && { score_threshold: options.scoreThreshold }),
        ...(options?.maxCandidates != null && { max_candidates: options.maxCandidates }),
      },
    }
  );
  return data;
}

// 主题情绪 tab 数据源：sum(w*t*net_density)/sum(w*t)，空值段落双向排除
export async function getTopicEmotion(
  novelId: string,
  taskId: string
): Promise<TopicEmotionResponse> {
  const { data } = await apiClient.get<TopicEmotionResponse>(
    `/api/novels/${novelId}/topics/emotion`,
    { params: { task_id: taskId } }
  );
  return data;
}
