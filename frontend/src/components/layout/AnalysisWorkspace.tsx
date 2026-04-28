import {
  Children,
  isValidElement,
  useEffect,
  useMemo,
  useState,
  type ReactElement,
  type ReactNode,
} from "react";
import { motion } from "framer-motion";
import type { NovelHeaderProps } from "@/components/common/NovelHeader";
import { AnalysisPageViewport } from "@/components/layout/AnalysisPageViewport";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/cn";

interface AnalysisWorkspaceProps {
  title: string;
  headerProps?: Omit<NovelHeaderProps, "title" | "className">;
  children: ReactNode;
  className?: string;
  headerClassName?: string;
  contentClassName?: string;
}

interface AnalysisWorkspaceTabsProps {
  children: ReactNode;
  defaultValue?: string;
  value?: string;
  onValueChange?: (value: string) => void;
  className?: string;
  listClassName?: string;
  panelsClassName?: string;
}

export interface AnalysisWorkspaceTabProps {
  value: string;
  label: string;
  children: ReactNode;
  className?: string;
}

/**
 * 2026-04-28，任务：分析详情页 slot 工作区收口
 * 新建原因：把单屏页面根布局和分析工作区统一成复合组件，页面只声明 header 与 slot 内容。
 */
function AnalysisWorkspaceRoot({
  title,
  headerProps,
  children,
  className,
  headerClassName,
  contentClassName,
}: AnalysisWorkspaceProps) {
  return (
    <AnalysisPageViewport
      title={title}
      headerProps={headerProps}
      className={className}
      headerClassName={headerClassName}
    >
      <div className={cn("flex min-h-0 flex-1 flex-col overflow-hidden py-1", contentClassName)}>{children}</div>
    </AnalysisPageViewport>
  );
}

/**
 * 2026-04-28，任务：分析详情页 slot 工作区收口
 * 新建原因：用 React 复合组件表达 tab slot，避免页面继续维护数组映射和重复面板骨架。
 */
function AnalysisWorkspaceTab({ children }: AnalysisWorkspaceTabProps) {
  return <>{children}</>;
}

/**
 * 2026-04-28，任务：分析详情页 slot 工作区收口
 * 新建原因：只允许 `AnalysisWorkspace.Tab` 进入 tab 编排，避免误把普通节点当成 tab item 解析。
 */
function isAnalysisWorkspaceTabElement(
  child: ReactNode,
): child is ReactElement<AnalysisWorkspaceTabProps> {
  return isValidElement(child) && child.type === AnalysisWorkspaceTab;
}

/**
 * 2026-04-28，任务：分析详情页 slot 工作区收口
 * 新建原因：统一 tabs 的激活状态、上下留白和 overflow 边界，不再让页面各自补滚动壳。
 */
function AnalysisWorkspaceTabs({
  children,
  defaultValue,
  value,
  onValueChange,
  className,
  listClassName,
  panelsClassName,
}: AnalysisWorkspaceTabsProps) {
  const tabItems = useMemo(
    () => Children.toArray(children).filter(isAnalysisWorkspaceTabElement),
    [children],
  );
  const firstValue = tabItems[0]?.props.value ?? "";
  const [internalValue, setInternalValue] = useState(defaultValue ?? firstValue);
  const isControlled = value !== undefined;
  const candidateValue = value ?? internalValue;
  const activeValue = tabItems.some((tabItem) => tabItem.props.value === candidateValue)
    ? candidateValue
    : firstValue;

  useEffect(() => {
    if (!isControlled && internalValue !== activeValue) {
      setInternalValue(activeValue);
    }
  }, [activeValue, internalValue, isControlled]);

  /**
   * 2026-04-28，任务：分析详情页 slot 工作区收口
   * 新建原因：受控与非受控两种模式都要共用同一套 tab 值切换逻辑。
   */
  function handleValueChange(nextValue: string) {
    if (!isControlled) {
      setInternalValue(nextValue);
    }
    onValueChange?.(nextValue);
  }

  if (tabItems.length === 0) {
    return null;
  }

  return (
    <Tabs
      value={activeValue}
      onValueChange={handleValueChange}
      className={cn("flex min-h-0 flex-1 flex-col overflow-hidden", className)}
    >
      <div className="shrink-0 px-2 pb-2 pt-1">
        <TabsList
          className={cn(
            "inline-flex h-auto w-max max-w-full flex-wrap justify-start gap-1 rounded-2xl bg-surface-hover/70 p-1",
            listClassName,
          )}
        >
          {tabItems.map((tabItem) => (
            <TabsTrigger key={tabItem.props.value} value={tabItem.props.value}>
              {tabItem.props.label}
            </TabsTrigger>
          ))}
        </TabsList>
      </div>

      <div
        className={cn(
          "relative min-h-0 flex-1 overflow-hidden px-2 pb-3 pt-1",
          panelsClassName,
        )}
      >
        {tabItems.map((tabItem) => (
          <TabsContent key={tabItem.props.value} value={tabItem.props.value} forceMount asChild>
            <motion.div
              initial={tabItem.props.value === activeValue ? { opacity: 0, y: 8 } : false}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.16, ease: "easeOut" }}
              className={cn(
                "mt-0 flex h-full min-h-0 flex-1 flex-col overflow-hidden rounded-[28px] p-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 data-[state=inactive]:hidden",
                tabItem.props.className,
              )}
            >
              <div className="flex min-h-0 flex-1 flex-col">{tabItem.props.children}</div>
            </motion.div>
          </TabsContent>
        ))}
      </div>
    </Tabs>
  );
}

export const AnalysisWorkspace = Object.assign(AnalysisWorkspaceRoot, {
  Tabs: AnalysisWorkspaceTabs,
  Tab: AnalysisWorkspaceTab,
});
