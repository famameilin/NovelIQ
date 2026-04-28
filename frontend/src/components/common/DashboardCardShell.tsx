import type { ReactNode } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/cn";

export type MetricAccent =
  | "primary"
  | "chart-1"
  | "chart-2"
  | "chart-3"
  | "chart-4"
  | "chart-5";

export const METRIC_ACCENT_CARD_CLASS_MAP: Record<MetricAccent, string> = {
  primary: "bg-gradient-to-br from-surface via-surface to-primary/15 hover:border-primary/30",
  "chart-1": "bg-gradient-to-br from-surface via-surface to-chart-1/15 hover:border-chart-1/30",
  "chart-2": "bg-gradient-to-br from-surface via-surface to-chart-2/15 hover:border-chart-2/30",
  "chart-3": "bg-gradient-to-br from-surface via-surface to-chart-3/15 hover:border-chart-3/30",
  "chart-4": "bg-gradient-to-br from-surface via-surface to-chart-4/15 hover:border-chart-4/30",
  "chart-5": "bg-gradient-to-br from-surface via-surface to-chart-5/15 hover:border-chart-5/30",
};

export const METRIC_ACCENT_BAR_CLASS_MAP: Record<MetricAccent, string> = {
  primary: "bg-primary",
  "chart-1": "bg-chart-1",
  "chart-2": "bg-chart-2",
  "chart-3": "bg-chart-3",
  "chart-4": "bg-chart-4",
  "chart-5": "bg-chart-5",
};

const METRIC_ACCENT_HOVER_TEXT_CLASS_MAP: Record<MetricAccent, string> = {
  primary: "hover:text-primary",
  "chart-1": "hover:text-chart-1",
  "chart-2": "hover:text-chart-2",
  "chart-3": "hover:text-chart-3",
  "chart-4": "hover:text-chart-4",
  "chart-5": "hover:text-chart-5",
};

interface DashboardCardShellProps {
  title?: string;
  icon?: ReactNode;
  accent?: MetricAccent;
  headerRight?: ReactNode;
  footer?: ReactNode;
  children: ReactNode;
  className?: string;
  contentClassName?: string;
  bodyClassName?: string;
  titleClassName?: string;
  showOrb?: boolean;
}

/**
 * 2026-04-21，任务：仪表盘组件视觉重构
 * 抽出 MetricCard 的共享视觉原语，避免业务卡片各自维护第二套卡片容器样式
 */
export function getMetricAccentColor(accent: MetricAccent, alpha?: number): string {
  return alpha == null ? `hsl(var(--${accent}))` : `hsl(var(--${accent}) / ${alpha})`;
}

/**
 * 2026-04-21，任务：仪表盘组件视觉重构
 * 统一业务卡片底部链接的 hover 色，避免组件内重复维护静态类映射
 */
export function getMetricAccentHoverTextClass(accent: MetricAccent): string {
  return METRIC_ACCENT_HOVER_TEXT_CLASS_MAP[accent];
}

/**
 * 2026-04-21，任务：仪表盘组件视觉重构
 * 让仪表盘业务组件统一复用 MetricCard 的容器、图标色块与 hover 反馈
 *
 * 2026-04-28，任务：分析详情页单屏布局收口
 * 修改原因：卡片 hover 的阴影过渡改为只过渡视觉属性，避免和位移动画错拍。
 */
export function DashboardCardShell({
  title,
  icon,
  accent = "primary",
  headerRight,
  footer,
  children,
  className,
  contentClassName,
  bodyClassName,
  titleClassName,
  showOrb = false,
}: DashboardCardShellProps) {
  return (
    <Card
      variant="elevated"
      className={cn(
        "relative overflow-hidden rounded-xl transition-[box-shadow,border-color,background-color] duration-200 hover:shadow-lg",
        METRIC_ACCENT_CARD_CLASS_MAP[accent],
        className
      )}
    >
      {showOrb && (
        <div
          className={cn(
            "pointer-events-none absolute rounded-full blur-3xl",
            accent === "primary"
              ? "-right-8 -top-10 h-28 w-28"
              : "-bottom-8 -right-8 h-24 w-24"
          )}
          style={{ backgroundColor: getMetricAccentColor(accent, 0.08) }}
        />
      )}
      <CardContent className={cn("relative flex h-full flex-col gap-3 p-4", contentClassName)}>
        {(title || icon || headerRight) && (
          <div className="flex items-start justify-between gap-3">
            <div className="flex min-w-0 items-center gap-3">
              {icon && (
                <div
                  className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl shadow-sm"
                  style={{
                    backgroundColor: getMetricAccentColor(accent, 0.12),
                    color: getMetricAccentColor(accent),
                  }}
                >
                  {icon}
                </div>
              )}
              {title && (
                <div className="min-w-0">
                  <p className={cn("text-sm font-semibold text-text", titleClassName)}>{title}</p>
                </div>
              )}
            </div>
            {headerRight}
          </div>
        )}

        <div className={cn("flex flex-1 flex-col", bodyClassName)}>{children}</div>

        {footer && <div className="mt-auto pt-1.5">{footer}</div>}
      </CardContent>
    </Card>
  );
}
