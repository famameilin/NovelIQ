// Stream Types (SSE) — 统一事件格式
// 定义后端 SSE 推送的流式消息类型，用于任务进度实时展示
// 所有进行中事件共用同一套数据结构
//   - 所有事件使用同一个 StreamEventData 结构
//   - 通过 action 字段区分事件类型（start/progress/complete/output/thinking）
//   - LLM 输出不再使用独立类型，自动获得 stage/sub_stage/chapter_id 上下文

export type SSEEventType =
  | "stage_start"      // action="start"（开始）
  | "stage_progress"   // action="progress"（进度）
  | "stage_complete"   // action="complete"（完成）
  | "llm_output"       // action="output"（输出）
  | "llm_thinking"     // action="thinking"（思考状态）
  | "tool_call"        // action="tool_call"（工具调用：content=工具名，status=started/success/failed）
  | "task_complete"
  | "task_error"
  | "task_cancelled"
  | "message";

export type ToolCallStatus = "started" | "success" | "failed";

export interface StreamEventData {
  action: string;        // 开始 / 进度 / 完成 / 输出 / 思考 / 工具调用
  stage: string;         // 预处理 / 标注 / 聚合 / 主题建模 / 诊断
  sub_stage: string;     // 第一阶段 / 第二阶段 / 第三阶段 / 第四阶段
  chapter_id?: number | null;  // 当前章节 ID（annotate 阶段有效）；HTTP 回填/终态事件不携带真实章节
  stream_id?: string | null; // llm_output/llm_thinking/tool_call 事件的显式流标识
  current: number;       // 当前章节编号
  total: number;        // 总章节数
  percent: number;      // 全局进度（stage 级别百分比）
  sub_percent: number;  // 子阶段进度（章节内 phase 进度，0-100）
  content: string;      // LLM 输出内容（output/thinking 时有值）；tool_call 时为工具名
  message: string;       // 可读描述
  status?: ToolCallStatus | null; // 工具调用状态（tool_call 事件专用）
}

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

export interface StreamMessage {
  type: SSEEventType;
  task_id: string;
  data: StreamEventData | TaskCompleteData | ErrorData | TaskCancelledData | Record<string, unknown>;
  timestamp: string;
}
