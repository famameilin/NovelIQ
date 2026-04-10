import { apiClient } from "./client";
import type {
  AnalysisStartResponse,
  AnalysisTask,
  TaskStatusResponse,
} from "./types";

export async function startAnalysis(
  novelId: string,
  taskId?: string
): Promise<AnalysisStartResponse> {
  const { data } = await apiClient.post<AnalysisStartResponse>(
    `/api/novels/${novelId}/analyze`,
    taskId ? { task_id: taskId } : undefined
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
  const { data } = await apiClient.get<{ novel_id: string; tasks: AnalysisTask[] }>(
    `/api/novels/${novelId}/tasks`
  );
  return data.tasks;
}

export async function deleteAnalysisTask(
  novelId: string,
  taskId: string
): Promise<void> {
  await apiClient.delete(`/api/novels/${novelId}/tasks/${taskId}`);
}

export async function cancelAnalysisTask(
  novelId: string,
  taskId: string
): Promise<{ task_id: string; status: string; message: string }> {
  const { data } = await apiClient.post<{
    task_id: string;
    status: string;
    message: string;
  }>(`/api/novels/${novelId}/tasks/${taskId}/cancel`);
  return data;
}

export async function batchDeleteTasks(
  novelId: string,
  taskIds: string[]
): Promise<{ deleted_count: number; failed_count: number }> {
  const { data } = await apiClient.post<{
    deleted_count: number;
    failed_count: number;
  }>(`/api/novels/${novelId}/tasks/batch-delete`, { task_ids: taskIds });
  return data;
}
