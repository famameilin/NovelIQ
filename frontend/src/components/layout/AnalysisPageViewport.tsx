import type { ReactNode } from "react";
import { PageContainer } from "@/components/layout/PageContainer";
import { NovelHeader, type NovelHeaderProps } from "@/components/common/NovelHeader";
import { cn } from "@/lib/cn";

interface AnalysisPageViewportProps {
  title: string;
  headerProps?: Omit<NovelHeaderProps, "title" | "className">;
  children: ReactNode;
  className?: string;
  headerClassName?: string;
  contentClassName?: string;
}

/**
 * 2026-04-28，任务：分析详情页单屏 Tabs 改造
 * 新建原因：统一分析详情页“顶部标题 + 剩余一屏工作区”的高度约束，
 * 防止后续新增卡片时继续把整页撑出视口。
 *
 * 2026-04-28，任务：分析详情页单屏布局收口
 * 修改原因：页面级上下留白从 `PageContainer` 下沉到分析页视口，避免和 tabs 工作区内边距重复叠加。
 */
export function AnalysisPageViewport({
  title,
  headerProps,
  children,
  className,
  headerClassName,
  contentClassName,
}: AnalysisPageViewportProps) {
  return (
    <PageContainer className={cn("overflow-hidden pt-6", className)}>
      <NovelHeader title={title} className={cn("mb-4 shrink-0", headerClassName)} {...headerProps} />
      <div className={cn("flex min-h-0 flex-1 flex-col overflow-hidden", contentClassName)}>{children}</div>
    </PageContainer>
  );
}
