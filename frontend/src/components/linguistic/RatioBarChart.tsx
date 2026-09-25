/**
 * RatioBarChart - 轻量比例分布条（纯 CSS，无需图表库）
 *
 * 用于词性/句式/词长等比例映射（键数量级 ≤ 30）；取值 0~1，按最大值归一显示。
 */
import type { LucideIcon } from "lucide-react";

import { DashboardCardShell } from "@/components/common/DashboardCardShell";

interface RatioBarChartProps {
  title: string;
  icon?: LucideIcon;
  accent?: "primary" | "chart-2" | "chart-3" | "chart-4" | "chart-5";
  ratios: Record<string, number> | null | undefined;
  emptyText?: string;
  className?: string;
  /** 值格式化（默认百分比一位小数） */
  formatValue?: (value: number) => string;
  /** 标签格式化；原始键仍通过 title 保留，便于定位未知枚举 */
  formatLabel?: (key: string) => string;
}

export function RatioBarChart({
  title,
  icon,
  accent = "chart-3",
  ratios,
  emptyText = "暂无数据",
  className,
  formatValue,
  formatLabel,
}: RatioBarChartProps) {
  const entries = Object.entries(ratios ?? {}).sort((left, right) => right[1] - left[1]);
  const max = entries.length > 0 ? Math.max(...entries.map(([, value]) => value)) : 0;
  const IconComponent = icon;

  return (
    <DashboardCardShell
      title={title}
      icon={IconComponent ? <IconComponent className="h-4 w-4" /> : undefined}
      accent={accent}
      className={className}
      bodyClassName="min-h-0"
    >
      {entries.length === 0 ? (
        <p className="py-8 text-center text-sm text-text-muted">{emptyText}</p>
      ) : (
        <ul className="space-y-2">
          {entries.map(([key, value]) => (
            <li key={key} className="flex items-center gap-3">
              <span className="w-28 shrink-0 truncate text-sm text-text" title={key}>
                {formatLabel ? formatLabel(key) : key}
              </span>
              <div className="h-2 min-w-0 flex-1 overflow-hidden rounded-full bg-surface-hover">
                <div
                  className="h-full rounded-full bg-chart-3"
                  style={{ width: `${max > 0 ? (value / max) * 100 : 0}%` }}
                />
              </div>
              <span className="w-16 shrink-0 text-right text-xs text-text-muted">
                {formatValue ? formatValue(value) : `${(value * 100).toFixed(1)}%`}
              </span>
            </li>
          ))}
        </ul>
      )}
    </DashboardCardShell>
  );
}
