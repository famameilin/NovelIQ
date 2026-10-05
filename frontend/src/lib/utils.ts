import type { TaskStatus } from "@/api/types";

/**
 * 按最大长度截断字符串，并补省略号
 */
export function truncate(str: string, maxLength: number): string {
  if (str.length <= maxLength) return str;
  return str.slice(0, maxLength) + "...";
}

/**
 * 把文件大小格式化为便于阅读的字符串
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
