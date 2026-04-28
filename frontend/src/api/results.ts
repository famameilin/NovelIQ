import { apiClient } from "./client";
import type {
  Character,
  ChunkAnnotation,
  ChunkCurvePoint,
  Topic,
  DiagnosisResult,
  ForeshadowingThread,
  GraphData,
  GraphEventsPageResponse,
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

// 获取人物关系图谱数据，包含节点、边、事件等信息
export async function getGraph(
  novelId: string,
  taskId: string
): Promise<GraphData> {
  const { data } = await apiClient.get<GraphData>(
    `/api/novels/${novelId}/graph`,
    { params: { task_id: taskId } }
  );
  return data;
}

export async function getGraphEvents(
  novelId: string,
  taskId: string,
  options?: { eventsCursor?: string | null; eventsLimit?: number }
): Promise<GraphEventsPageResponse> {
  const { data } = await apiClient.get<GraphEventsPageResponse>(
    `/api/novels/${novelId}/graph/events`,
    {
      params: {
        task_id: taskId,
        ...(options?.eventsCursor ? { events_cursor: options.eventsCursor } : {}),
        ...(options?.eventsLimit != null ? { events_limit: options.eventsLimit } : {}),
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
