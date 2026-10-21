/** 分析任务详情和小说结果使用同一真实任务身份 */
import type {TaskStatus} from "@/api/types";

export const analysisTaskPath = (novelId: string, taskId: string) =>
  `/novels/${encodeURIComponent(novelId)}/analysis/${encodeURIComponent(taskId)}`;

export const novelTaskPath = (novelId: string, taskId: string) =>
  `/novels/${encodeURIComponent(novelId)}?task_id=${encodeURIComponent(taskId)}`;

export const taskPagePath = (novelId: string, taskId: string, status: TaskStatus) =>
  status === "completed" ? novelTaskPath(novelId, taskId) : analysisTaskPath(novelId, taskId);
