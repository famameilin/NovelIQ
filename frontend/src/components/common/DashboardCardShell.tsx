import type { ReactNode } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/cn";

import type { MetricAccent } from "./metric-accent";
import { METRIC_ACCENT_CARD_CLASS_MAP } from "./metric-accent";
import { getMetricAccentColor, getMetricAccentHoverTextClass, METRIC_ACCENT_BAR_CLASS_MAP } from "./metric-accent";

export type { MetricAccent };
// eslint-disable-next-line react-refresh/only-export-components -- re-exports from metric-accent.ts
export { METRIC_ACCENT_CARD_CLASS_MAP, METRIC_ACCENT_BAR_CLASS_MAP, getMetricAccentColor, getMetricAccentHoverTextClass };

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
