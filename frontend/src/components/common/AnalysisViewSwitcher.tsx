import type { LucideIcon } from "lucide-react";

import { cn } from "@/lib/cn";

export interface AnalysisViewOption<T extends string> {
  value: T;
  label: string;
  icon?: LucideIcon;
}

interface AnalysisViewSwitcherProps<T extends string> {
  value: T;
  options: readonly AnalysisViewOption<T>[];
  onValueChange: (value: T) => void;
  label: string;
  className?: string;
}

/**
 * 2026-08-31，作用：统一分析页主视图的分段切换控件
 * 简要说明：使用真实按钮和 aria-pressed 表达当前桌面视图并支持键盘操作
 */
export function AnalysisViewSwitcher<T extends string>({
  value,
  options,
  onValueChange,
  label,
  className,
}: AnalysisViewSwitcherProps<T>) {
  return (
    <div
      role="group"
      aria-label={label}
      className={cn(
        "inline-flex items-center gap-1 rounded-lg border border-border/70 bg-surface-hover/65 p-1",
        className,
      )}
    >
      {options.map((option) => {
        const Icon = option.icon;
        const isActive = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            aria-pressed={isActive}
            onClick={() => onValueChange(option.value)}
            className={cn(
              "flex min-h-9 items-center gap-2 rounded-md px-3 text-sm font-medium transition-colors",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/45",
              isActive
                ? "bg-surface text-text shadow-sm"
                : "text-text-muted hover:bg-surface/70 hover:text-text",
            )}
          >
            {Icon ? <Icon className="h-4 w-4" aria-hidden="true" /> : null}
            <span>{option.label}</span>
          </button>
        );
      })}
    </div>
  );
}
