/**
 * Tab 级聚合 API —— 前端每 tab 一个 API
 *
 * 响应只含复合数据与展示主体；既有单源端点（/emotion-trend、/timeline、
 * /topics/series|shifts|emotion、/linguistic/features|word2vec、/characters、
 * /graph/changes、/diagnosis、/foreshadowing-trees）直接作为所属 tab 的 API，
 * 继续从 results.ts / linguistic.ts 调用，不在此重复包装。
 */
import { apiClient } from "./client";
import type {
  CharacterFunctionTabResponse,
  DashboardTabResponse,
  GraphNetworkTabResponse,
  LinguisticEntitiesTabResponse,
  RhythmTabResponse,
  TopicsOverviewTabResponse,
} from "./types";

/** 统一 queryKey 前缀：["tabs", novelId, taskId, tab, ...params] */
export function tabQueryKey(tab: string, novelId: string | undefined, taskId: string | null, ...rest: unknown[]) {
  return ["tabs", novelId, taskId, tab, ...rest];
}

/** 仪表盘 tab：四组聚合指标 + 章节汇总 + 主题词 + 诊断 + 情绪趋势 */
export async function getDashboardTab(novelId: string, taskId: string): Promise<DashboardTabResponse> {
  const { data } = await apiClient.get<DashboardTabResponse>(`/api/novels/${novelId}/tabs/dashboard`, {
    params: { task_id: taskId },
  });
  return data;
}

/** 节奏张力 tab：段落曲线（max_points 展示降采样）+ 叙事结构高潮参数 */
export async function getRhythmTab(
  novelId: string,
  taskId: string,
  options?: { maxPoints?: number }
): Promise<RhythmTabResponse> {
  const { data } = await apiClient.get<RhythmTabResponse>(`/api/novels/${novelId}/tabs/rhythm`, {
    params: {
      task_id: taskId,
      ...(options?.maxPoints != null && { max_points: options.maxPoints }),
    },
  });
  return data;
}

/** 功能与焦点 tab：角色功能分布 + 诊断焦点结构切片 */
export async function getCharacterFunctionTab(
  novelId: string,
  taskId: string
): Promise<CharacterFunctionTabResponse> {
  const { data } = await apiClient.get<CharacterFunctionTabResponse>(
    `/api/novels/${novelId}/tabs/character-function`,
    { params: { task_id: taskId } }
  );
  return data;
}

/** 图谱 tab：图快照 + 登场次数 + 图算法指标 + 变化总数 */
export async function getGraphNetworkTab(
  novelId: string,
  taskId: string,
  options?: { chapterId?: number }
): Promise<GraphNetworkTabResponse> {
  const { data } = await apiClient.get<GraphNetworkTabResponse>(`/api/novels/${novelId}/tabs/graph-network`, {
    params: {
      task_id: taskId,
      ...(options?.chapterId != null ? { chapter_id: options.chapterId } : {}),
    },
  });
  return data;
}

/** 主题总览 tab：主题词 + 全书/章节完整分布 + TextRank 关键词 */
export async function getTopicsOverviewTab(novelId: string, taskId: string): Promise<TopicsOverviewTabResponse> {
  const { data } = await apiClient.get<TopicsOverviewTabResponse>(`/api/novels/${novelId}/tabs/topics-overview`, {
    params: { task_id: taskId },
  });
  return data;
}

/** 实体与短语 tab：实体类型计数 + 高频实体名 + 固定短语统计 */
export async function getLinguisticEntitiesTab(
  novelId: string,
  taskId: string
): Promise<LinguisticEntitiesTabResponse> {
  const { data } = await apiClient.get<LinguisticEntitiesTabResponse>(
    `/api/novels/${novelId}/tabs/linguistic-entities`,
    { params: { task_id: taskId } }
  );
  return data;
}
