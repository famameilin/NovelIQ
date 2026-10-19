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
import { type EventCardDetail, type EventTreeListResponse, type NarrativeSource, type PlotlineChange, type PlotlineDimension, type PlotlineTimelineResponse } from "./narrativeTypes";

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
  options: { throughChapterId?: number; windowStartChapterId?: number; windowEndChapterId?: number; subjectId?: string; dimension?: PlotlineDimension; q?: string; cursor?: string; limit?: number; sourceFactId?: string; signal?: AbortSignal } = {},
): Promise<PlotlineTimelineResponse> {
  const { signal, ...query } = options;
  const { data } = await apiClient.get<PlotlineTimelineResponse>(
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

/** 事件树列表仅顶层大事件分页，页面不再发送搜索、章节筛选或父级展开参数 */
export async function getEventTrees(options: { novelId: string; taskId: string; cursor?: string; limit?: number; signal?: AbortSignal }): Promise<EventTreeListResponse> {
  const { data } = await apiClient.get<EventTreeListResponse>(`/api/novels/${options.novelId}/event-trees`, { params: { task_id: options.taskId, ...definedParams({ cursor: options.cursor, limit: options.limit }) }, signal: options.signal });
  return data;
}

/** 循环 cursor 完整消费全部页，按 counts 校验收齐；收不齐、游标重复或运行身份变化都视为读取失败 */
export async function getEventTreeBook(novelId: string, taskId: string, signal?: AbortSignal): Promise<EventTreeListResponse> {
  const first = await getEventTrees({ novelId, taskId, limit: 50, signal });
  const events = new Map(first.events.map(event => [event.event_id, event]));
  const seenCursors = new Set<string>();
  let cursor = first.next_cursor;
  while (cursor) {
    if (seenCursors.has(cursor)) throw new Error("事件树分页游标重复，无法收齐全书事件");
    seenCursors.add(cursor);
    const page = await getEventTrees({ novelId, taskId, limit: 50, cursor, signal });
    if (page.run_id !== first.run_id) throw new Error("事件树分页运行身份变化，无法合并全书事件");
    page.events.forEach(event => events.set(event.event_id, event));
    cursor = page.next_cursor;
  }
  const counts = first.counts;
  if (events.size !== counts.top_level_events || counts.top_level_events + counts.child_events !== counts.all_events) {
    throw new Error(`事件树分页未收齐：已读 ${events.size} 个顶层事件，契约声明顶层 ${counts.top_level_events} / 全部 ${counts.all_events}`);
  }
  return { ...first, events: [...events.values()], next_cursor: null };
}

export async function getEventTreeNode(novelId: string, taskId: string, nodeId: string, signal?: AbortSignal): Promise<EventCardDetail> {
  const { data } = await apiClient.get<EventCardDetail>(`/api/novels/${novelId}/event-trees/nodes/${encodeURIComponent(nodeId)}`, { params: { task_id: taskId }, signal });
  return data;
}

export async function getTimelineChange(novelId: string, taskId: string, changeId: string, throughChapterId: number, signal?: AbortSignal): Promise<PlotlineChange> {
  const { data } = await apiClient.get<PlotlineChange>(`/api/novels/${novelId}/timeline/changes/${encodeURIComponent(changeId)}`, { params: { task_id: taskId, through_chapter_id: throughChapterId }, signal });
  return data;
}

export async function getNarrativeSource(novelId: string, taskId: string, context: { page: "timeline" | "event-trees"; id: string; chapterId?: number; throughChapterId?: number; kind?: "event" | "declaration" }, signal?: AbortSignal): Promise<NarrativeSource> {
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
export async function getChapterEventDetail(novelId: string, taskId: string, chapterId: number, declarationId: string): Promise<import("./narrativeTypes").ChapterEventDetail> {
  const { data } = await apiClient.get<import("./narrativeTypes").ChapterEventDetail>(
    `/api/novels/${novelId}/event-forest/chapters/${chapterId}/nodes/${encodeURIComponent(declarationId)}`,
    { params: { task_id: taskId } },
  );
  return data;
}
