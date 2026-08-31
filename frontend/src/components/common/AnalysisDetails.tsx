import { useState, type ReactNode, type SyntheticEvent } from "react";
import { ChevronDown } from "lucide-react";

import { cn } from "@/lib/cn";

interface AnalysisDetailsProps {
  children: ReactNode;
  title?: string;
  description?: string;
  defaultOpen?: boolean;
  lazy?: boolean;
  className?: string;
}

/**
 * 2026-08-31，作用：承载分析页中保留的技术口径和次级指标
 * 简要说明：主视图保持可读，用户仍可按需展开查看完整分析数据
 */
export function AnalysisDetails({
  children,
  title = "分析详情",
  description,
  defaultOpen = false,
  lazy = false,
  className,
}: AnalysisDetailsProps) {
  const [isOpen, setIsOpen] = useState(defaultOpen);
  const [hasOpened, setHasOpened] = useState(defaultOpen);

  /**
   * 2026-08-31，作用：延迟挂载折叠区中的图表内容
   * 简要说明：等待容器展开后再初始化图表，避免零尺寸画布和空白图表
   */
  function handleToggle(event: SyntheticEvent<HTMLDetailsElement>) {
    const nextOpen = event.currentTarget.open;
    setIsOpen(nextOpen);
    if (nextOpen && !hasOpened) setHasOpened(true);
  }

  return (
    <details
      open={isOpen}
      onToggle={handleToggle}
      className={cn("group rounded-lg border border-border/70 bg-surface/60", className)}
    >
      <summary className="flex cursor-pointer list-none items-center justify-between gap-4 px-4 py-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary/45 [&::-webkit-details-marker]:hidden">
        <span className="min-w-0">
          <span className="block text-sm font-medium text-text">{title}</span>
          {description ? <span className="mt-0.5 block text-xs leading-5 text-text-muted">{description}</span> : null}
        </span>
        <ChevronDown
          className="h-4 w-4 shrink-0 text-text-muted transition-transform group-open:rotate-180"
          aria-hidden="true"
        />
      </summary>
      {!lazy || hasOpened ? <div className="border-t border-border/60 px-4 py-4">{children}</div> : null}
    </details>
  );
}
