import axios from "axios";

/**
 * 结果页现在会收到两类需要显式分流的 API 错误：
 * 1. `AnalysisNotCompleteError`，表示任务尚未进入可读终态；
 * 2. `diagnosis_rerun_required`，表示旧 diagnosis 合同已经失效
 * 页面层统一通过这里识别，避免每个页面各自手写一套脆弱的 axios 取值链
 */

type AxiosErrorPayload = {
  detail?: string | { code?: string; reason?: string | null; message?: string };
  error_type?: string;
  status_code?: number;
};

/**
 * 统一识别“分析尚未完成”的后端状态机错误，供各结果页切换到专用等待态
 */
export function isAnalysisNotCompleteError(error: unknown): boolean {
  if (!axios.isAxiosError<AxiosErrorPayload>(error)) {
    return false;
  }
  return error.response?.status === 400 && error.response?.data?.error_type === "AnalysisNotCompleteError";
}

/**
 * 提取 AnalysisNotCompleteError 携带的运行状态（failed/running/pending 等）。
 * 优先读后端结构化字段 run_status，缺失时从 detail 文本“当前状态: X”解析兜底。
 */
export function getAnalysisNotCompleteRunStatus(error: unknown): string | null {
  if (!axios.isAxiosError<AxiosErrorPayload & { run_status?: string }>(error)) {
    return null;
  }
  const data = error.response?.data;
  if (typeof data?.run_status === "string" && data.run_status) {
    return data.run_status;
  }
  const detail = typeof data?.detail === "string" ? data.detail : null;
  const match = detail?.match(/当前状态:\s*([A-Za-z_]+)/);
  return match ? match[1] : null;
}

/**
 * 统一识别 diagnosis 焦点合同失效时的 rerun gate，避免页面继续把旧 run 渲染成成功态
 */
export function isDiagnosisRerunRequiredError(error: unknown): boolean {
  if (!axios.isAxiosError<AxiosErrorPayload>(error)) {
    return false;
  }
  return (
    error.response?.status === 409 &&
    typeof error.response?.data?.detail === "object" &&
    error.response.data.detail?.code === "diagnosis_rerun_required"
  );
}
