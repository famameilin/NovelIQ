/**
 * 2026-08-16 统一指标格式化
 * 集中处理可空数字、百分比和全书进度，保证展示层不把缺失数据伪装成零
 */

export const SAMPLE_INSUFFICIENT_LABEL = "样本不足";

/**
 * 2026-08-16 格式化可空数字
 * 空值和非有限值统一返回样本不足，其余值按指定小数位显示
 */
export function formatNullableNumber(
  value: number | null | undefined,
  digits = 2,
  fallback = SAMPLE_INSUFFICIENT_LABEL,
): string {
  return value == null || !Number.isFinite(value) ? fallback : value.toFixed(digits);
}

/**
 * 2026-08-16 格式化可空比例
 * 将 0 到 1 的比例转换为百分比，缺失时保留诚实的样本不足文案
 */
export function formatNullablePercent(
  value: number | null | undefined,
  digits = 0,
  fallback = SAMPLE_INSUFFICIENT_LABEL,
): string {
  return value == null || !Number.isFinite(value)
    ? fallback
    : `${(value * 100).toFixed(digits)}%`;
}

/**
 * 2026-08-16 格式化全书进度跨度
 * 后端以 0 到 1 的进度距离返回值，界面统一标注全书进度百分比
 */
export function formatProgressSpan(
  value: number | null | undefined,
  digits = 1,
  fallback = SAMPLE_INSUFFICIENT_LABEL,
): string {
  return value == null || !Number.isFinite(value)
    ? fallback
    : `全书 ${(value * 100).toFixed(digits)}%`;
}

/**
 * 2026-08-16 返回统一的样本不足文案
 * 通过函数名表达指标缺少有效样本的展示语义
 */
export function formatSampleInsufficient(): string {
  return SAMPLE_INSUFFICIENT_LABEL;
}
