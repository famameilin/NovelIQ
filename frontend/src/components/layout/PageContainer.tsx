import { motion } from "framer-motion";
import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

const pageVariants = {
  initial: { opacity: 0, y: 20 },
  animate: { opacity: 1, y: 0, transition: { duration: 0.3 } },
  exit: { opacity: 0, y: -10, transition: { duration: 0.2 } },
};

interface PageContainerProps {
  children: ReactNode;
  className?: string;
}

/**
 * 2026-04-28，任务：分析详情页单屏布局收口
 * 修改原因：移除全局纵向内边距，让具体页面自行决定顶部/底部留白，避免和 tabs 工作区重复叠加。
 */
export function PageContainer({ children, className }: PageContainerProps) {
  return (
    <motion.main
      variants={pageVariants}
      initial="initial"
      animate="animate"
      exit="exit"
      className={cn("mx-auto flex h-full w-full max-w-[1400px] flex-col px-6", className)}
    >
      {children}
    </motion.main>
  );
}
