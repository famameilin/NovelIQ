import { apiClient } from "./client";
import type {
  Character,
  ChunkAnnotation,
  ChunkCurvePoint,
  Topic,
  DiagnosisResult,
  ForeshadowingThread,
  GraphData,
  GraphChangesPageResponse,
  TimelineResponse,
  NarrativeStructureMetrics,
  EmotionStatsMetrics,
  CharacterStatsMetrics,
  StyleStatsMetrics,
} from "./types";

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

export async function getChunkCurves(
  novelId: string,
  taskId: string,
  options?: { page?: number; page_size?: number }
): Promise<ChunkCurvePoint[]> {
  const { data } = await apiClient.get<ChunkCurvePoint[]>(
    `/api/novels/${novelId}/chunk-curves`,
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

export async function getChunkAnnotations(
  novelId: string,
  taskId: string
): Promise<ChunkAnnotation[]> {
  const { data } = await apiClient.get<ChunkAnnotation[]>(
    `/api/novels/${novelId}/chunk-annotations`,
    { params: { task_id: taskId } }
  );
  return data;
}

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

// 获取指定章节边界的图谱快照
export async function getGraph(
  novelId: string,
  taskId: string,
  options?: { chapterId?: number; graphVersionId?: string }
): Promise<GraphData> {
  const { data } = await apiClient.get<GraphData>(
    `/api/novels/${novelId}/graph`,
    {
      params: {
        task_id: taskId,
        ...(options?.chapterId != null ? { chapter_id: options.chapterId } : {}),
        ...(options?.graphVersionId ? { graph_version_id: options.graphVersionId } : {}),
      },
    }
  );
  return data;
}

// 按章节倒序获取实体状态与关系变化
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
        ...(options?.changesLimit != null ? { changes_limit: options.changesLimit } : {}),
      },
    }
  );
  return data;
}

// 获取叙事时间轴数据，支持 include_curve 参数
export async function getTimeline(
  novelId: string,
  taskId: string,
  options?: { includeCurve?: boolean }
): Promise<TimelineResponse> {
  const { data } = await apiClient.get<TimelineResponse>(
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

export async function getNarrativeStructure(
  novelId: string,
  taskId: string
): Promise<NarrativeStructureMetrics> {
  const { data } = await apiClient.get<NarrativeStructureMetrics>(
    `/api/novels/${novelId}/metrics/narrative-structure`,
    { params: { task_id: taskId } }
  );
  return data;
}

export async function getEmotionStats(
  novelId: string,
  taskId: string
): Promise<EmotionStatsMetrics> {
  const { data } = await apiClient.get<EmotionStatsMetrics>(
    `/api/novels/${novelId}/metrics/emotion-stats`,
    { params: { task_id: taskId } }
  );
  return data;
}

export async function getCharacterStats(
  novelId: string,
  taskId: string
): Promise<CharacterStatsMetrics> {
  const { data } = await apiClient.get<CharacterStatsMetrics>(
    `/api/novels/${novelId}/metrics/character-stats`,
    { params: { task_id: taskId } }
  );
  return data;
}

export async function getStyleStats(
  novelId: string,
  taskId: string
): Promise<StyleStatsMetrics> {
  const { data } = await apiClient.get<StyleStatsMetrics>(
    `/api/novels/${novelId}/metrics/style-stats`,
    { params: { task_id: taskId } }
  );
  return data;
}
