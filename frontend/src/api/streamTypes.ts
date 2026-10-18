// Stream Types (SSE) — 后端 SSE 流式消息类型：所有进行中事件共用 StreamEventData，
// 按 action 区分类型（start/progress/complete/output/thinking）

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
  | "work_reset"
  | "task_reset"
  | "chapter_reset"
  | "pipeline_progress"
  | "reconnect_required"
  | "message";

export type ToolCallStatus = "started" | "success" | "failed";

export interface StreamEventData {
  action: string;        // 开始 / 进度 / 完成 / 输出 / 思考 / 工具调用
  stage: string;         // 预处理 / 标注 / 聚合 / 主题建模 / 诊断
  sub_stage: string;     // 标注=章内角色（annotation/entity/event/metric）；诊断=案例角色（case/report）
  chapter_id?: number | null;  // 当前章节 ID（annotate 阶段有效）；HTTP 回填/终态事件不携带真实章节
  invocation_id?: string | null;
  message_id?: string | null;
  stream_id?: string | null; // llm_output/llm_thinking/tool_call 事件的显式流标识
  current: number;       // 当前章节编号
  total: number;         // 总章节数
  percent: number;       // 全局进度（stage 级别百分比）
  sub_percent: number;   // 子阶段进度（章节内 phase 进度，0-100）
  content: string;      // LLM 输出内容（output/thinking 时有值）；tool_call 时为工具名
  message: string;       // 可读描述
  status?: ToolCallStatus | null; // 工具调用状态（tool_call 事件专用）
}

export interface ErrorData {
  error: string;
  stage?: string;
}

/** 流作用域取实际阶段上下文：标注=章+角色，诊断=阶段+案例角色；执行身份只看 invocation_id */
export function buildStreamExecutionScope(data: Pick<StreamEventData, "stage" | "chapter_id" | "sub_stage">): string {
  return `${data.stage}:${data.chapter_id || 0}:${data.sub_stage || ""}`;
}
