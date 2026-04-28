import { apiClient } from "./client";
import type {
  AnalysisStartResponse,
  AnalysisTask,
  BatchDeleteTasksResponse,
  TaskStatusResponse,
} from "./types";

// 显式创建并启动新任务
export async function createAnalysisTask(
  novelId: string
): Promise<AnalysisStartResponse> {
  const { data } = await apiClient.post<AnalysisStartResponse>(
    `/api/novels/${novelId}/tasks`
  );
  return data;
}

// 仅继续指定 pending/failed 任务
export async function resumeAnalysisTask(
  novelId: string,
  taskId: string
): Promise<AnalysisStartResponse> {
  const { data } = await apiClient.post<AnalysisStartResponse>(
    `/api/novels/${novelId}/tasks/${taskId}/resume`
  );
  return data;
}

// 单任务状态查询走专用路由
export async function getTaskStatus(
  novelId: string,
  taskId: string
): Promise<TaskStatusResponse> {
  const { data } = await apiClient.get<TaskStatusResponse>(
    `/api/novels/${novelId}/tasks/${taskId}/status`
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
): Promise<BatchDeleteTasksResponse> {
  const { data } = await apiClient.post<BatchDeleteTasksResponse>(
    `/api/novels/${novelId}/tasks/batch-delete`,
    { task_ids: taskIds }
  );
  return data;
}
