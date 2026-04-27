import axios from "axios";

/**
 * 创建时间: 2026-04-27
 * 创建者: Codex
 * 任务: protagonist-focus-contract-review-fixes-round5
 * 说明: 结果页现在会收到两类需要显式分流的 API 错误：
 * 1. `AnalysisNotCompleteError`，表示任务尚未进入可读终态；
 * 2. `diagnosis_rerun_required`，表示旧 diagnosis 合同已经失效。
 * 页面层统一通过这里识别，避免每个页面各自手写一套脆弱的 axios 取值链。
 */

type AxiosErrorPayload = {
  detail?: string | { code?: string; reason?: string | null; message?: string };
  error_type?: string;
  status_code?: number;
};

/**
 * 创建时间: 2026-04-27
 * 创建者: Codex
 * 任务: protagonist-focus-contract-review-fixes-round5
 * 说明: 统一识别“分析尚未完成”的后端状态机错误，供各结果页切换到专用等待态。
 */
export function isAnalysisNotCompleteError(error: unknown): boolean {
  if (!axios.isAxiosError<AxiosErrorPayload>(error)) {
    return false;
  }
  return error.response?.status === 400 && error.response?.data?.error_type === "AnalysisNotCompleteError";
}

/**
 * 创建时间: 2026-04-27
 * 创建者: Codex
 * 任务: protagonist-focus-contract-review-fixes-round5
 * 说明: 统一识别 diagnosis 焦点合同失效时的 rerun gate，避免页面继续把旧 run 渲染成成功态。
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
