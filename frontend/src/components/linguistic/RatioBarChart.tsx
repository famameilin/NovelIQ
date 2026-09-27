/**
 * RatioBarChart - 语言特征分布视图
 * 少量类别展示构成与明细；较多类别使用双列排行，长列表均衡分页。
 */
import { useState } from "react";
import type { LucideIcon } from "lucide-react";

import { DashboardCardShell } from "@/components/common/DashboardCardShell";
import { PagedControls } from "@/components/common/PagedControls";

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
  pageSize?: number;
  columns?: 1 | 2;
  /** 仅用于互斥类别；可把计数或比例按所列类别总量显示构成。 */
  presentation?: "ranking" | "composition";
}

const SEGMENT_COLORS = [
  { className: "bg-chart-3", css: "hsl(var(--chart-3))" },
  { className: "bg-chart-2", css: "hsl(var(--chart-2))" },
  { className: "bg-chart-4", css: "hsl(var(--chart-4))" },
  { className: "bg-chart-5", css: "hsl(var(--chart-5))" },
  { className: "bg-chart-1", css: "hsl(var(--chart-1))" },
] as const;

/** 每页数量尽量接近，避免固定切片产生只有一两项的末页。 */
function balancedPage<T>(items: readonly T[], requestedPage: number, pageSize: number) {
  const pageCount = Math.ceil(items.length / Math.max(1, pageSize));
  const page = Math.min(requestedPage, Math.max(1, pageCount));
  const baseSize = pageCount > 0 ? Math.floor(items.length / pageCount) : 0;
  const extra = pageCount > 0 ? items.length % pageCount : 0;
  const start = (page - 1) * baseSize + Math.min(page - 1, extra);
  const count = baseSize + (page <= extra ? 1 : 0);
  return { page, pageCount, start, items: items.slice(start, start + count) };
}

function compositionGradient(entries: readonly [string, number][], total: number) {
  if (total <= 0) return undefined;
  let start = 0;
  const stops = entries.map(([, value], index) => {
    const end = start + Math.max(0, value) / total * 100;
    const stop = `${SEGMENT_COLORS[index % SEGMENT_COLORS.length].css} ${start}% ${end}%`;
    start = end;
    return stop;
  });
  return `conic-gradient(${stops.join(", ")})`;
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
  pageSize = 8,
  columns = 1,
  presentation = "ranking",
}: RatioBarChartProps) {
  const [requestedPage, setPage] = useState(1);
  const entries = Object.entries(ratios ?? {}).sort((left, right) => right[1] - left[1]);
  const { page, pageCount, start, items } = balancedPage(entries, requestedPage, pageSize);
  const max = Math.max(0, ...entries.map(([, value]) => value));
  const total = entries.reduce((sum, [, value]) => sum + Math.max(0, value), 0);
  const isComposition = presentation === "composition" && columns === 2 && pageCount === 1 && entries.length <= 5;
  const isTwoColumnRanking = columns === 2 && items.length > 5;
  const IconComponent = icon;
  const displayLabel = (key: string) => formatLabel ? formatLabel(key) : key;
  const displayValue = (value: number) => formatValue ? formatValue(value) : `${(value * 100).toFixed(1)}%`;

  return (
    <DashboardCardShell
      title={title}
      icon={IconComponent ? <IconComponent className="h-4 w-4" /> : undefined}
      accent={accent}
      headerRight={entries.length > 0 ? <span className="text-xs text-text-muted">共 {entries.length} 类</span> : undefined}
      className={className}
      contentClassName="flex h-full flex-col"
      bodyClassName="min-h-0 flex-1 gap-3"
    >
      {entries.length === 0 ? (
        <p className="flex flex-1 items-center justify-center text-sm text-text-muted">{emptyText}</p>
      ) : isComposition ? (
        <div className="grid min-h-0 flex-1 grid-cols-2 items-center gap-6" data-testid="distribution-composition">
          <div className="flex h-full min-h-0 items-center justify-center">
            <div
              role="img"
              aria-label={`${title}构成图`}
              className="relative aspect-square shrink-0 rounded-full bg-surface-hover"
              style={{ height: "min(100%, 440px)", background: compositionGradient(entries, total) }}
            >
              <div className="absolute inset-[21%] flex flex-col items-center justify-center rounded-full bg-surface shadow-inner">
                <strong className="text-3xl font-semibold tabular-nums text-text">{entries.length}</strong>
                <span className="text-xs text-text-muted">种类别</span>
              </div>
            </div>
          </div>
          <div className="min-w-0">
            {total > 0 && entries.length <= 3 && <div className="mb-3 border-l-2 border-chart-3 pl-3">
              <p className="text-xs text-text-muted">所列类别中占比最高</p>
              <p className="mt-1 flex items-baseline gap-3 text-text">
                <span className="truncate text-sm font-medium" title={entries[0][0]}>{displayLabel(entries[0][0])}</span>
                <strong className="text-xl font-semibold tabular-nums">{(Math.max(0, entries[0][1]) / total * 100).toFixed(1)}%</strong>
              </p>
            </div>}
            <ul className="grid gap-2">
              {items.map(([key, value], index) => {
                const color = SEGMENT_COLORS[(start + index) % SEGMENT_COLORS.length];
                return <li key={key} className="min-w-0">
                  <div className="mb-1 flex items-center gap-2 text-sm">
                    <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${color.className}`} aria-hidden="true" />
                    <span className="min-w-0 flex-1 truncate text-text" title={key}>{displayLabel(key)}</span>
                    <span className="shrink-0 font-medium tabular-nums text-text">{displayValue(value)}</span>
                  </div>
                  <div className="ml-4 h-1.5 rounded-full bg-surface-hover">
                    <div className={`h-full rounded-full ${color.className}`} style={{ width: `${max > 0 ? Math.max(0, value) / max * 100 : 0}%` }} />
                  </div>
                </li>;
              })}
            </ul>
          </div>
        </div>
      ) : (
        <ul className={isTwoColumnRanking
          ? "grid min-h-0 flex-1 auto-rows-fr grid-cols-2 gap-x-6 gap-y-1"
          : "grid min-h-0 flex-1 auto-rows-fr gap-y-1"} data-testid="distribution-ranking">
          {items.map(([key, value], index) => {
            const color = SEGMENT_COLORS[(start + index) % SEGMENT_COLORS.length];
            return <li key={key} className="flex min-h-0 items-center gap-3 border-b border-border/50 px-2 last:border-b-0">
              <span className="w-28 shrink-0 truncate text-sm text-text" title={key}>{displayLabel(key)}</span>
              <div className="h-2 min-w-0 flex-1 rounded-full bg-surface-hover">
                <div className={`h-full rounded-full ${color.className}`} style={{ width: `${max > 0 ? Math.max(0, value) / max * 100 : 0}%` }} />
              </div>
              <span className="w-16 shrink-0 text-right text-xs tabular-nums text-text-muted">{displayValue(value)}</span>
            </li>;
          })}
        </ul>
      )}
      <PagedControls page={page} pageCount={pageCount} onPageChange={setPage} label={title} />
    </DashboardCardShell>
  );
}
