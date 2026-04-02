import type { TaskStatus } from "@/api/types";

/**
 * Format a number to a fixed number of decimal places
 */
export function formatNumber(value: number, decimals = 2): string {
  return value.toFixed(decimals);
}

/**
 * Format a percentage value (0-1) to display string
 */
export function formatPercent(value: number, decimals = 1): string {
  return `${(value * 100).toFixed(decimals)}%`;
}

/**
 * Truncate a string to a maximum length with ellipsis
 */
export function truncate(str: string, maxLength: number): string {
  if (str.length <= maxLength) return str;
  return str.slice(0, maxLength) + "...";
}

/**
 * Validate hex color format
 */
export function isValidHexColor(hex: string): boolean {
  return /^#[0-9A-Fa-f]{6}$/.test(hex);
}

/**
 * Format file size to human readable string
 */
export function formatFileSize(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
}

// ============================================================
// Task Status Config
// ============================================================

type BadgeVariant = "default" | "secondary" | "success" | "destructive" | "outline";

export interface TaskStatusDisplay {
  label: string;
  variant: BadgeVariant;
}

export const taskStatusConfig: Record<TaskStatus, TaskStatusDisplay> = {
  pending: { label: "等待中", variant: "outline" },
  chunking: { label: "分块中", variant: "secondary" },
  annotating: { label: "标注中", variant: "secondary" },
  aggregating: { label: "聚合中", variant: "secondary" },
  diagnosing: { label: "诊断中", variant: "secondary" },
  completed: { label: "已完成", variant: "success" },
  failed: { label: "失败", variant: "destructive" },
};
