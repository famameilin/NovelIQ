/**
 * 语言特征 API —— 词法句法 / 词向量 tab 数据源
 *
 * 实体与短语 tab 走 api/tabs.ts 的 getLinguisticEntitiesTab（聚合切片）；
 * 本模块承接单源端点（/linguistic/features、/linguistic/word2vec）。
 */
import { apiClient } from "./client";
import type { LinguisticFeaturesResponse, Word2VecStatsResponse } from "./types";

/** 词法句法 tab：词性/词长/句式/依存聚合（book 与 chapters 两级恒返回） */
export async function getLinguisticFeatures(
  novelId: string,
  taskId: string
): Promise<LinguisticFeaturesResponse> {
  const { data } = await apiClient.get<LinguisticFeaturesResponse>(
    `/api/novels/${novelId}/linguistic/features`,
    { params: { task_id: taskId } }
  );
  return data;
}

/** 词向量 tab：模型契约 + POS 覆盖率/质心 + 组间余弦相似度矩阵 */
export async function getLinguisticWord2vec(
  novelId: string,
  taskId: string
): Promise<Word2VecStatsResponse> {
  const { data } = await apiClient.get<Word2VecStatsResponse>(
    `/api/novels/${novelId}/linguistic/word2vec`,
    { params: { task_id: taskId } }
  );
  return data;
}
