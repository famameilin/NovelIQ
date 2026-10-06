import { apiClient } from "./client";

export interface PipelineSnapshot {
  completed_chapters: number;
  total_chapters: number;
  saved_work_count: number;
  case_states: Record<"pending" | "resolved" | "deferred" | "contested", number>;
  cases: Array<{
    case_id: string;
    description: string;
    state: "pending" | "resolved" | "deferred" | "contested";
  }>;
  connections: Array<{
    connection_id: string;
    parent_node_id: string;
    node_id: string;
    type: string;
    author_work_id: string;
    parent_description: string;
    description: string;
    parent_chapter_id: number;
    chapter_id: number;
  }>;
  works: Array<{work_id: string; chapter_id: number; role: string; state: string; invocation_id: string}>;
}

export async function getPipelineSnapshot(novelId: string, taskId: string): Promise<PipelineSnapshot> {
  const { data } = await apiClient.get<PipelineSnapshot>(`/api/novels/${novelId}/pipeline`, { params: { task_id: taskId } });
  return data;
}
