import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

export interface AnalysisMetricItem {
  label: string;
  value: ReactNode;
  description?: string;
}

interface AnalysisMetricStripProps {
  items: readonly AnalysisMetricItem[];
  className?: string;
}

/**
 * 2026-08-31，作用：展示分析页最常用的摘要指标
 * 简要说明：以同一条带承载关键数字，避免为每个指标重复创建独立卡片
 */
export function AnalysisMetricStrip({ items, className }: AnalysisMetricStripProps) {
  return (
    <dl
      className={cn(
        "grid grid-cols-4 gap-px overflow-hidden rounded-lg border border-border/70 bg-border/70",
        className,
      )}
    >
      {items.map((item, index) => (
        <div
          key={`${item.label}-${index}`}
          className="min-w-0 bg-surface px-4 py-3"
        >
          <dt className="text-xs text-text-muted">{item.label}</dt>
          <dd
            className="mt-1 truncate text-lg font-semibold text-text"
            title={typeof item.value === "string" ? item.value : undefined}
          >
            {item.value}
          </dd>
          {item.description ? <p className="mt-1 text-xs leading-5 text-text-muted">{item.description}</p> : null}
        </div>
      ))}
    </dl>
  );
}
