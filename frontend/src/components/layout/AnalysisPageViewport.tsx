import type { ReactNode } from "react";
import { PageContainer } from "@/components/layout/PageContainer";
import { NovelHeader, type NovelHeaderProps } from "@/components/common/NovelHeader";
import { cn } from "@/lib/cn";

interface AnalysisPageViewportProps {
  title: string;
  headerProps?: Omit<NovelHeaderProps, "title" | "className">;
  children: ReactNode;
  documentFlow?: boolean;
  className?: string;
  headerClassName?: string;
  contentClassName?: string;
}

/**
 * 2026-04-28，作用：统一分析页标题、宽度、留白和滚动边界
 * 简要说明：默认约束为固定视口，文档流模式把纵向滚动交给 AppLayout 外层
 */
export function AnalysisPageViewport({
  title,
  headerProps,
  children,
  documentFlow = false,
  className,
  headerClassName,
  contentClassName,
}: AnalysisPageViewportProps) {
  return (
    <PageContainer
      className={cn(
        documentFlow
          ? "h-auto min-h-full max-w-full overflow-visible px-8 py-2 2xl:px-10"
          : "max-w-full overflow-hidden px-8 py-2 2xl:px-10",
        className,
      )}
    >
      <NovelHeader title={title} className={cn("mb-4 shrink-0", headerClassName)} {...headerProps} />
      <div
        className={cn(
          documentFlow
            ? "flex min-h-0 flex-col overflow-visible"
            : "flex min-h-0 flex-1 flex-col overflow-hidden",
          contentClassName,
        )}
      >
        {children}
      </div>
    </PageContainer>
  );
}
