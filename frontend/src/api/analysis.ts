import { apiClient } from "./client";
import type {
  AnalysisStartResponse,
  AnalysisTask,
  TaskStatusResponse,
} from "./types";

export async function startAnalysis(
  novelId: string
): Promise<AnalysisStartResponse> {
  const { data } = await apiClient.post<AnalysisStartResponse>(
    `/api/novels/${novelId}/analyze`
  );
  return data;
}

export async function reanalyze(
  novelId: string
): Promise<AnalysisStartResponse> {
  const { data } = await apiClient.post<AnalysisStartResponse>(
    `/api/novels/${novelId}/reanalyze`
  );
  return data;
}

export async function getAnalysisStatus(
  novelId: string,
  taskId: string
): Promise<TaskStatusResponse> {
  const { data } = await apiClient.get<TaskStatusResponse>(
    `/api/novels/${novelId}/status`,
    { params: { task_id: taskId } }
  );
  return data;
}

export async function getAnalysisTasks(
  novelId: string
): Promise<AnalysisTask[]> {
  const { data } = await apiClient.get<AnalysisTask[]>(
    `/api/novels/${novelId}/tasks`
  );
  return data;
}

export async function deleteAnalysisTask(
  novelId: string,
  taskId: string
): Promise<void> {
  await apiClient.delete(`/api/novels/${novelId}/tasks/${taskId}`);
}
