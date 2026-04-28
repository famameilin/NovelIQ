import type { ReactNode } from "react";
import { AnalysisWorkspace } from "@/components/layout/AnalysisWorkspace";

export interface AnalysisTabItem {
  value: string;
  label: string;
  children: ReactNode;
}

interface AnalysisTabsProps {
  tabs: AnalysisTabItem[];
  defaultValue?: string;
  className?: string;
  listClassName?: string;
  contentClassName?: string;
}

/**
 * 2026-04-28，任务：分析详情页单屏 Tabs 改造
 * 修改原因：改为委托 `AnalysisWorkspace` 复合组件，兼容旧数组 API，同时把 slot 工作区作为唯一实现。
 */
export function AnalysisTabs({
  tabs,
  defaultValue,
  className,
  listClassName,
  contentClassName,
}: AnalysisTabsProps) {
  if (tabs.length === 0) {
    return null;
  }

  return (
    <AnalysisWorkspace.Tabs
      defaultValue={defaultValue}
      className={className}
      listClassName={listClassName}
      panelsClassName={contentClassName}
    >
      {tabs.map((tab) => (
        <AnalysisWorkspace.Tab key={tab.value} value={tab.value} label={tab.label}>
          {tab.children}
        </AnalysisWorkspace.Tab>
      ))}
    </AnalysisWorkspace.Tabs>
  );
}
