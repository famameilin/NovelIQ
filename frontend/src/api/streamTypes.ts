// ============================================================
// Stream Types (WebSocket)
// ============================================================

// 创建时间: 2026-04-07
// 创建者: GLM-5
// 任务: WebSocket 流式消息类型定义
// 说明: 定义后端 WebSocket 推送的流式消息类型，用于任务进度实时展示

export type StreamMessageType =
  | "task_start"
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

// 创建时间: 2026-04-07
// 创建者: GLM-5
// 任务: WebSocket 流式消息类型定义
// 说明: 阶段进度详情，用于 stage_progress 消息

export interface ProgressDetail {
  stage: string;
  sub_stage?: string;
  phase?: string;  // 当前 phase 名称（如 "phase1", "phase2", "phase3", "phase4"）
  current: number;
  total: number;
  percent: number;
  message?: string;
}

// ============================================================
// LLM Output Data
// ============================================================

// 创建时间: 2026-04-07
// 创建者: GLM-5
// 任务: WebSocket 流式消息类型定义
// 说明: LLM 输出数据，用于 llm_output 和 llm_thinking 消息

export interface LLMOutputData {
  phase: string;
  chunk_id?: number;
  content: string;
}

// ============================================================
// Error Data
// ============================================================

// 创建时间: 2026-04-07
// 创建者: GLM-5
// 任务: WebSocket 流式消息类型定义
// 说明: 错误数据，用于 task_error 消息

export interface ErrorData {
  error: string;
  stage?: string;
}

// ============================================================
// Stream Message
// ============================================================

// 创建时间: 2026-04-07
// 创建者: GLM-5
// 任务: WebSocket 流式消息类型定义
// 说明: WebSocket 消息统一格式，data 字段根据 type 不同对应不同类型

export interface StreamMessage {
  type: StreamMessageType;
  task_id: string;
  data: ProgressDetail | LLMOutputData | ErrorData | Record<string, unknown>;
  timestamp: string;
}
