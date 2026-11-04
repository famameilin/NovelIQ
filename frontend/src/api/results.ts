import { indexEventQueues } from "./eventQueues";
import { apiClient } from "./client";
import type {
  DiagnosisResult,
  ForeshadowingTree,
  GraphChangesPageResponse,
  EmotionTrendWindow,
  TopicEmotionResponse,
  TopicSeriesResponse,
  TopicShiftResponse,
} from "./types";
import { type EventCardDetail, type EventTreeListResponse, type NarrativeSource, type PlotlineChange, type PlotlineDimension, type PlotlineStatesResponse, type PlotlineSubjectsResponse, type PlotlineTimelineResponse } from "./narrativeTypes";

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
  options: { throughChapterId?: number; windowStartChapterId?: number; windowEndChapterId?: number; subjectId?: string; dimension?: PlotlineDimension; q?: string; cursor?: string; limit?: number; sourceFactId?: string; metaOnly?: boolean; signal?: AbortSignal } = {},
): Promise<PlotlineTimelineResponse> {
  const { signal, ...query } = options;
  const { data } = await apiClient.get<PlotlineTimelineResponse>(
    `/api/novels/${novelId}/timeline`,
    {
      params: {
        task_id: taskId,
        ...definedParams({ through_chapter_id: query.throughChapterId, window_start_chapter_id: query.windowStartChapterId, window_end_chapter_id: query.windowEndChapterId, subject_id: query.subjectId, dimension: query.dimension, q: query.q, cursor: query.cursor, limit: query.limit, source_fact_id: query.sourceFactId, meta_only: query.metaOnly }),
      },
      signal,
    }
  );
  return data;
}

/** 截点状态来源：summary 只取每维最近一个主体，其余按偏移分页 */
export async function getTimelineStates(
  novelId: string,
  taskId: string,
  options: { throughChapterId?: number; subjectId?: string; dimension?: PlotlineDimension; q?: string; cursor?: string; limit?: number; summary?: boolean; signal?: AbortSignal } = {},
): Promise<PlotlineStatesResponse> {
  const { signal, ...query } = options;
  const { data } = await apiClient.get<PlotlineStatesResponse>(
    `/api/novels/${novelId}/timeline/states`,
    {
      params: { task_id: taskId, ...definedParams({ through_chapter_id: query.throughChapterId, subject_id: query.subjectId, dimension: query.dimension, q: query.q, cursor: query.cursor, limit: query.limit, summary: query.summary }) },
      signal,
    }
  );
  return data;
}

/** 变化主体选择器按名称搜索，不下载全书主体 */
export async function getTimelineSubjects(
  novelId: string,
  taskId: string,
  options: { throughChapterId?: number; dimension?: PlotlineDimension; q?: string; cursor?: string; limit?: number; signal?: AbortSignal } = {},
): Promise<PlotlineSubjectsResponse> {
  const { signal, ...query } = options;
  const { data } = await apiClient.get<PlotlineSubjectsResponse>(
    `/api/novels/${novelId}/timeline/subjects`,
    {
      params: { task_id: taskId, ...definedParams({ through_chapter_id: query.throughChapterId, dimension: query.dimension, q: query.q, cursor: query.cursor, limit: query.limit }) },
      signal,
    }
  );
  return data;
}

function definedParams(values: Record<string, unknown>) {
  return Object.fromEntries(Object.entries(values).filter(([, value]) => value !== undefined));
}

/** 一次读取全书真实事件、包含树和结果关联 */
export async function getEventTrees(options: { novelId: string; taskId: string; signal?: AbortSignal }): Promise<EventTreeListResponse> {
  const { data } = await apiClient.get<EventTreeListResponse>(`/api/novels/${options.novelId}/event-trees`, { params: { task_id: options.taskId }, signal: options.signal });
  return data;
}

/** 数量不一致时明确读取失败，避免把缺失节点的响应当作完整事件树 */
export async function getEventTreeBook(novelId: string, taskId: string, signal?: AbortSignal): Promise<EventTreeListResponse> {
  const book = await getEventTrees({ novelId, taskId, signal });
  indexEventQueues(book);
  return book;
}

export async function getEventTreeNode(novelId: string, taskId: string, nodeId: string, signal?: AbortSignal): Promise<EventCardDetail> {
  const { data } = await apiClient.get<EventCardDetail>(`/api/novels/${novelId}/event-trees/nodes/${encodeURIComponent(nodeId)}`, { params: { task_id: taskId }, signal });
  return data;
}

export async function getTimelineChange(novelId: string, taskId: string, changeId: string, throughChapterId: number, signal?: AbortSignal): Promise<PlotlineChange> {
  const { data } = await apiClient.get<PlotlineChange>(`/api/novels/${novelId}/timeline/changes/${encodeURIComponent(changeId)}`, { params: { task_id: taskId, through_chapter_id: throughChapterId }, signal });
  return data;
}

export async function getNarrativeSource(novelId: string, taskId: string, context: { page: "timeline" | "event-trees"; id: string; chapterId?: number; throughChapterId?: number; kind?: "event" }, signal?: AbortSignal): Promise<NarrativeSource> {
  const resource = context.page === "timeline" ? "changes" : "nodes";
  const { data } = await apiClient.get<NarrativeSource>(`/api/novels/${novelId}/${context.page}/${resource}/${encodeURIComponent(context.id)}/source`, { params: { task_id: taskId, ...definedParams({ chapter_id: context.chapterId, through_chapter_id: context.throughChapterId, kind: context.kind }) }, signal });
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

/** 当前章详情按原声明身份读取，全书归属仅作为关联信息 */
export async function getChapterEventDetail(novelId: string, taskId: string, chapterId: number, eventId: string): Promise<import("./narrativeTypes").ChapterEventDetail> {
  const { data } = await apiClient.get<import("./narrativeTypes").ChapterEventDetail>(
    `/api/novels/${novelId}/event-forest/chapters/${chapterId}/nodes/${encodeURIComponent(eventId)}`,
    { params: { task_id: taskId } },
  );
  return data;
}
