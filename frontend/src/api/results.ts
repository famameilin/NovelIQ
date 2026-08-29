import { apiClient } from "./client";
import type {
  Character,
  Topic,
  DiagnosisResult,
  ForeshadowingThread,
  GraphChangesPageResponse,
  EventTimelineResponse,
  EmotionTrendWindow,
} from "./types";

// 角色：角色排行/角色表 tab 的数据源（单源端点直接作为 tab API）
export async function getCharacters(
  novelId: string,
  taskId: string,
  options?: { page?: number; page_size?: number }
): Promise<Character[]> {
  const { data } = await apiClient.get<Character[]>(
    `/api/novels/${novelId}/characters`,
    {
      params: {
        task_id: taskId,
        ...(options?.page != null && { page: options.page }),
        ...(options?.page_size != null && { page_size: options.page_size }),
      },
    }
  );
  return data;
}

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

// 主题 Top-5 口径（含主题词）：主题总览 tab 的词云数据源
export async function getTopics(
  novelId: string,
  taskId: string
): Promise<Topic[]> {
  const { data } = await apiClient.get<Topic[]>(
    `/api/novels/${novelId}/topics`,
    { params: { task_id: taskId } }
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

// 伏笔线程台账：Setup 台账 tab 的数据源（展示主体原样透传）
export async function getForeshadowingThreads(
  novelId: string,
  taskId: string
): Promise<ForeshadowingThread[]> {
  const { data } = await apiClient.get<ForeshadowingThread[]>(
    `/api/novels/${novelId}/foreshadowing-threads`,
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

// 获取叙事时间轴数据，支持 include_curve 参数（仅新森林合同 EventTimelineResponse）；
// 时间轴/节点详情 tab 的数据源
export async function getTimeline(
  novelId: string,
  taskId: string,
  options?: { includeCurve?: boolean }
): Promise<EventTimelineResponse> {
  const { data } = await apiClient.get<EventTimelineResponse>(
    `/api/novels/${novelId}/timeline`,
    {
      params: {
        task_id: taskId,
        include_curve: options?.includeCurve ?? true,
      },
    }
  );
  return data;
}
