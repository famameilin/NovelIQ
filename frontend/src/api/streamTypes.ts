/** 模型通信与任务状态事件 */
export type SSEEventType = "llm_output" | "llm_thinking" | "tool_call" | "task_complete" | "task_error" | "task_cancelled" | "task_reset" | "reconnect_required" | "message" | "snapshot" | "stage_state" | "stage_progress" | "capacity" | "agent_activity" | "work_saved" | "work_reset" | "chapter_reset" | "task_state" | "notification_status";
export type ToolCallStatus = "started" | "success" | "failed";
export interface StreamEventData {
  action: string; agent_type?: string; chapter_id?: number | null; invocation_id?: string | null;
  message_id?: string | null; stream_id?: string | null; tool_call_id?: string;
  content: string; message: string; status?: ToolCallStatus | null;
}
