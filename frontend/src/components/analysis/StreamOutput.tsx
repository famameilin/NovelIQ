/**
 * StreamOutput - LLM 输出实时显示组件
 *
 * 创建时间: 2026-04-07
 * 创建者: GLM-5
 * 任务: LLM 输出实时显示组件
 * 说明: 实时显示 LLM 流式输出内容，支持自动滚动和行数限制
 *
 * 修改时间: 2026-04-10
 * 修改者: TraeAI
 * 任务: 前端流式输出markdown渲染
 * 修改内容: 新增 react-markdown + remark-gfm 支持 GFM 渲染，默认保留最近 1000 行
 */
import { useRef, useEffect, useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useStreamStore } from "@/store/streamStore";
import { cn } from "@/lib/cn";

export interface StreamOutputProps {
  taskId: string;
  maxLines?: number;
  className?: string;
}

const STAGE_LABELS: Record<string, string> = {
  preprocess: "预处理",
  annotate: "标注分析",
  aggregate: "数据聚合",
  "topic-model": "主题建模",
  diagnose: "诊断报告",
};

export function StreamOutput({
  taskId,
  maxLines = 1000,
  className,
}: StreamOutputProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const llmOutputs = useStreamStore((state) => state.llmOutputs);
  const progress = useStreamStore((state) => state.progress);
  const currentTaskId = useStreamStore((state) => state.currentTaskId);

  const outputContent = useMemo(() => {
    if (!progress || currentTaskId !== taskId) return null;

    const allChunks: string[] = [];
    llmOutputs.forEach((chunks, key) => {
      if (key.startsWith(`${progress.stage}-`)) {
        allChunks.push(...chunks);
      }
    });

    if (allChunks.length === 0) return null;

    const allLines = allChunks.join("\n").split("\n");
    return allLines.slice(-maxLines).join("\n");
  }, [llmOutputs, progress, maxLines, currentTaskId, taskId]);

  useEffect(() => {
    if (containerRef.current && outputContent) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [outputContent]);

  if (!progress || currentTaskId !== taskId) return null;

  if (!outputContent) {
    return (
      <div
        className={cn(
          "rounded-lg border border-border bg-surface-secondary p-4",
          "text-sm text-text-muted",
          className
        )}
      >
        <div className="flex items-center gap-2 mb-2">
          <div className="h-2 w-2 animate-pulse rounded-full bg-primary" />
          <span>正在执行 {STAGE_LABELS[progress.stage] || progress.stage}</span>
        </div>
        {progress.message && (
          <p className="text-xs text-text-muted">{progress.message}</p>
        )}
        <p className="text-xs text-text-muted mt-2">
          LLM 输出将在模型推理阶段显示...
        </p>
      </div>
    );
  }

  return (
    <AnimatePresence mode="wait">
      <motion.div
        ref={containerRef}
        key="stream-output"
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -10 }}
        transition={{ duration: 0.3, ease: "easeOut" }}
        className={cn(
          "flex-1 overflow-auto rounded-lg border border-border bg-surface-secondary p-4",
          "font-mono text-sm text-text-secondary whitespace-pre-wrap break-words",
          className
        )}
        aria-label="LLM 输出内容"
        aria-live="polite"
        aria-atomic="false"
      >
        <Markdown remarkPlugins={[remarkGfm]}>{outputContent}</Markdown>
      </motion.div>
    </AnimatePresence>
  );
}
