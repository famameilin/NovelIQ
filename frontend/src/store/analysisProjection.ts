/** 已确认通知的纯归并逻辑，快照替换状态，增量才追加输出 */
import type { TaskStatus } from "@/api/types";

export const analysisStages = ["preprocess", "annotate", "linguistic", "aggregate", "topic-model", "diagnose"] as const;
export type AnalysisStage = typeof analysisStages[number];
export interface StageRecord {
  stage: string; status: string; message?: string; steps?: Record<string, ProgressRecord>;
}
export interface ProgressRecord { current?: number | null; total?: number | null; unit?: string; status?: string; message?: string; }
export interface CapacityModel { model_id: string; capacity: number; }
export interface CapacitySeat { model_id: string; slot: number; reservation_id: string; run_id: string; work_id: string; foreign?: boolean; }
export interface ToolRecord { tool_call_id: string; content: string; message: string; status: string; }
export interface ExecutionRecord {
  invocation_id: string; work_id?: string; model_id?: string; reservation_id?: string; stage?: string;
  sub_stage?: string; chapter_id?: number | null; case_id?: string | null; activity?: string; error?: string;
  output: string; thinking: string; tools: Record<string, ToolRecord>; truncated: boolean;
  details?: {case_ids?: string[]; unsubmitted_case_ids?: string[]};
}
export interface AnalysisProjection {
  cursor: number; run_id: string; task_id?: string; status: TaskStatus | null; stage: string; error: string | null;
  stages: Record<string, StageRecord>; models: CapacityModel[]; seats: CapacitySeat[];
  executions: Record<string, ExecutionRecord>; sync_pending?: boolean;
}
export interface AnalysisNotice extends ProgressRecord {
  task_id?: string; run_id?: string; stage?: string; sub_stage?: string; invocation_id?: string;
  work_id?: string; model_id?: string; reservation_id?: string; chapter_id?: number; case_id?: string;
  content?: string; activity?: string; error?: string; tool_call_id?: string;
  models?: CapacityModel[]; seats?: CapacitySeat[]; details?: ExecutionRecord["details"];
}
export const emptyAnalysisProjection = (): AnalysisProjection => ({
  cursor: 0, run_id: "", status: null, stage: "", error: null, stages: {}, models: [], seats: [], executions: {},
});

export function mergeAnalysisNotice(current: AnalysisProjection, type: string, data: AnalysisNotice, seq: number): AnalysisProjection {
  if (seq <= current.cursor) return current;
  const next = {...current, cursor: seq, run_id: data.run_id || current.run_id};
  if (type === "task_reset") { next.status = "pending"; next.error = null; }
  if (["task_state", "task_complete", "task_error", "task_cancelled"].includes(type)) {
    next.status = data.status as TaskStatus; next.error = data.error ?? null;
  }
  if (type === "capacity") { next.models = data.models ?? []; next.seats = data.seats ?? []; }
  if (type === "stage_state" && data.stage) {
    next.stages = {...current.stages, [data.stage]: {...current.stages[data.stage], ...data} as StageRecord};
    if (["running", "saving", "failed", "cancelled"].includes(data.status ?? "")) next.stage = data.stage;
  }
  if (type === "stage_progress" && data.stage) {
    const stage = current.stages[data.stage] ?? {stage: data.stage, status: "running"};
    next.stages = {...current.stages, [data.stage]: {...stage, steps: {...stage.steps, [data.sub_stage || "processing"]: data}}};
  }
  if (!data.invocation_id) return next;
  const id = data.invocation_id;
  const execution: ExecutionRecord = {...(current.executions[id] ?? {
    invocation_id: id, output: "", thinking: "", tools: {}, truncated: false,
  })};
  for (const key of ["work_id", "model_id", "reservation_id", "stage", "sub_stage", "chapter_id", "case_id", "details"] as const) {
    const value = data[key];
    if (value != null && value !== "") Object.assign(execution, {[key]: value});
  }
  if (type === "llm_output" || type === "llm_thinking") {
    const key = type === "llm_output" ? "output" : "thinking";
    const text = execution[key] + (data.content ?? "");
    execution[key] = text.slice(-8192); execution.truncated ||= text.length > 8192;
    execution.activity = key === "output" ? "generating" : "thinking";
  }
  if (type === "tool_call") {
    if (data.tool_call_id) {
      const tools = {...execution.tools, [data.tool_call_id]: data as ToolRecord};
      while (Object.keys(tools).length > 64) delete tools[Object.keys(tools)[0]];
      execution.tools = tools;
    }
    execution.activity = data.status === "started" ? "tool" : "working";
  }
  if (type === "agent_activity") {
    execution.activity = data.activity;
    execution.error = data.activity === "error" ? data.message : undefined;
  }
  if (type === "work_saved") execution.activity = "saved";
  next.executions = {...current.executions, [id]: execution};
  const occupied = new Set(next.seats.filter(seat => !seat.foreign).map(seat => seat.reservation_id));
  while (Object.keys(next.executions).length > 128) {
    const removable = Object.keys(next.executions).find(key => !occupied.has(next.executions[key].reservation_id ?? ""));
    if (!removable) break;
    delete next.executions[removable];
  }
  return next;
}
