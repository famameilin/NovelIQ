// ============================================================
// Stream Types (SSE) — 统一事件格式
// ============================================================

// 创建时间: 2026-04-07
// 创建者: GLM-5
// 任务: WebSocket 流式消息类型定义
// 说明: 定义后端 SSE 推送的流式消息类型，用于任务进度实时展示

// 修改时间: 2026-04-09
// 创建者: GLM-5
// 任务: refactor/sse-unified-event-bus
// 修改内容: 统一 SSE 数据格式
//   - 所有事件使用同一个 StreamEventData 结构
//   - 通过 action 字段区分事件类型（start/progress/complete/output/thinking）
//   - LLM 输出不再使用独立类型，自动获得 stage/sub_stage/chunk_id 上下文

// ============================================================
// SSE Event Types — 由 action 字段映射而来
// ============================================================

export type SSEEventType =
  | "stage_start"      // action="start"
  | "stage_progress"   // action="progress"
  | "stage_complete"   // action="complete"
  | "llm_output"       // action="output"
  | "llm_thinking"     // action="thinking"
  | "task_complete"
  | "task_error"
  | "task_cancelled"
  | "message";

// ============================================================
// 统一事件数据格式 — 后端 StreamEvent.to_dict()
// ============================================================

export interface StreamEventData {
  action: string;        // start / progress / complete / output / thinking
  stage: string;         // preprocess / annotate / aggregate / topic-model / diagnose
  sub_stage: string;     // phase1 / phase2 / phase3 / phase4
  chunk_id: number;      // 当前 chunk ID（annotate 阶段有效）
  stream_id?: string | null; // 并行 LLM 流分组标识（Phase3 并行 batch 时使用）
  current: number;       // 当前 chunk 编号
  total: number;        // 总 chunk 数
  percent: number;      // 全局进度（stage 级别百分比）
  sub_percent: number;  // 子阶段进度（chunk 内 phase 进度，0-100）
  content: string;      // LLM 输出内容（output/thinking 时有值）
  message: string;       // 人类可读描述
}

// ============================================================
// 终止事件数据格式（task_complete/task_error/task_cancelled）
// ============================================================

export interface TaskCompleteData {
  stage: string;
  percent: number;
  message: string;
}

export interface ErrorData {
  error: string;
  stage?: string;
}

export interface TaskCancelledData {
  stage: string;
  message: string;
}

// ============================================================
// Stream Message — SSE 消息信封
// ============================================================

export interface StreamMessage {
  type: SSEEventType;
  task_id: string;
  data: StreamEventData | TaskCompleteData | ErrorData | TaskCancelledData | Record<string, unknown>;
  timestamp: string;
}
