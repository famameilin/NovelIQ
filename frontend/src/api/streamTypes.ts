// ============================================================
// Stream Types (SSE)
// ============================================================

// 创建时间: 2026-04-07
// 创建者: GLM-5
// 任务: WebSocket 流式消息类型定义
// 说明: 定义后端 SSE 推送的流式消息类型，用于任务进度实时展示

// 修改时间: 2026-04-09
// 创建者: GLM-5
// 任务: sse-architecture-review
// 修改内容: 前后端类型对齐
//   - stage_complete 加入 StreamMessageType
//   - ProgressDetail: sub_stage 和 phase 改为必填（后端总是传空字符串）
//   - ErrorData 增加 stage 字段

export type StreamMessageType =
  | "stage_start"
  | "stage_progress"
  | "stage_complete"
  | "llm_output"
  | "llm_thinking"
  | "task_complete"
  | "task_error"
  | "task_cancelled";

// ============================================================
// Progress Detail
// ============================================================

export interface ProgressDetail {
  stage: string;
  sub_stage: string;
  phase: string;
  current: number;
  total: number;
  percent: number;
  message: string;
}

// ============================================================
// LLM Output Data
// ============================================================

export interface LLMOutputData {
  phase: string;
  chunk_id?: number;
  content: string;
}

// ============================================================
// Error Data
// ============================================================

export interface ErrorData {
  error: string;
  stage?: string;
}

// ============================================================
// Stream Message
// ============================================================

export interface StreamMessage {
  type: StreamMessageType;
  task_id: string;
  data: ProgressDetail | LLMOutputData | ErrorData | Record<string, unknown>;
  timestamp: string;
}
