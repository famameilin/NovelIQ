import type { TaskStatus } from "@/api/types";

/**
 * 按固定小数位格式化数字
 */
export function formatNumber(value: number, decimals = 2): string {
  return value.toFixed(decimals);
}

/**
 * 把百分比数值（0-1）格式化为展示字符串
 */
export function formatPercent(value: number, decimals = 1): string {
  return `${(value * 100).toFixed(decimals)}%`;
}

/**
 * 按最大长度截断字符串，并补省略号
 */
export function truncate(str: string, maxLength: number): string {
  if (str.length <= maxLength) return str;
  return str.slice(0, maxLength) + "...";
}

/**
 * 校验十六进制颜色格式
 */
export function isValidHexColor(hex: string): boolean {
  return /^#[0-9A-Fa-f]{6}$/.test(hex);
}

/**
 * 把文件大小格式化为人类可读字符串
 */
export function formatFileSize(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
}

type BadgeVariant = "default" | "secondary" | "success" | "destructive" | "outline";

export interface TaskStatusDisplay {
  label: string;
  variant: BadgeVariant;
}

export const taskStatusConfig: Record<TaskStatus, TaskStatusDisplay> = {
  pending: { label: "等待中", variant: "outline" },
  running: { label: "运行中", variant: "secondary" },
  cancelling: { label: "取消中", variant: "secondary" },
  cancelled: { label: "已取消", variant: "outline" },
  completed: { label: "已完成", variant: "success" },
  failed: { label: "失败", variant: "destructive" },
};
