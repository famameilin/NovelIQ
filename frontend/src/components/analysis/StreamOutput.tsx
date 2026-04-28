/**
 * StreamOutput - LLM 输出实时显示组件
 *
 * 实时显示 LLM 流式输出内容，支持自动滚动和行数限制
 *
 * - 按 stream group 展示 Phase3 并行流，避免多个 batch 继续拼成一段混流文本
 * - 主面板默认只展示当前活跃流，其余流收口为摘要和切换入口
 * - 详细多流查看改放进 Dialog，避免主页面高度被并行输出撑爆
 *
 * - 改为直接消费 store 中的有界文本缓冲，避免每次渲染都全量 join/split 历史片段
 * - 细化最近流选择与摘要长度计算，减少长时间后台恢复后的主线程负担
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  buildLLMOutputScopeKey,
  type LLMStreamGroup,
  useStreamStore,
} from "@/store/streamStore";
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

const ANNOTATION_PHASE_TAB_SUBSTAGES = new Set(["phase1", "phase2", "phase3", "phase4"]);

/**
 * 主视图和弹窗都要复用“仅保留最近 N 行”的裁剪逻辑，避免并行流文本无限增长
 */
function _limitMarkdownLines(content: string, maxLines: number): string {
  const allLines = content.split("\n");
  return allLines.slice(-maxLines).join("\n");
}

/**
 * UI 不直接暴露后端 batch 编号，而是按当前 scope 首次出现顺序生成稳定的“并行流 N”标签
 */
function _buildStreamLabel(streamNumber: number): string {
  return `并行流 ${streamNumber}`;
}

/**
 * phase 切换很快时，当前 scope 可能暂时还没有新流；
 * 这时回退到同 chunk 的最近输出，避免用户明明收到了 SSE 却看到空面板
 */
function _isSameChunkScope(group: LLMStreamGroup, stage: string, chunkId: number): boolean {
  return group.stage === stage && group.chunkId === chunkId;
}

/**
 * 同 chunk 跨 phase 回退时，输出和思考可能分别落在不同 group；
 * 主面板应各自取最近的非空内容，避免 thinking 明明已到却仍显示空态
 */
function _pickLatestGroupWithContent(
  groups: LLMStreamGroup[],
  kind: "output" | "thinking",
): LLMStreamGroup | null {
  let latestGroup: LLMStreamGroup | null = null;
  for (const group of groups) {
    const content = kind === "output" ? group.outputText : group.thinkingText;
    if (!content.trim()) {
      continue;
    }
    if (!latestGroup || group.lastUpdatedAt >= latestGroup.lastUpdatedAt) {
      latestGroup = group;
    }
  }
  return latestGroup;
}

/**
 * Markdown 详情面板需要在流式追加时自动滚到末尾，但不影响主页面整体布局高度
 */
function StreamMarkdownPanel({
  content,
  className,
}: {
  content: string;
  className?: string;
}) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [content]);

  return (
    <div
      ref={containerRef}
      className={cn(
        "h-full overflow-auto rounded-lg border border-border bg-surface-secondary p-4",
        "font-mono text-sm text-text-secondary whitespace-pre-wrap break-words",
        className,
      )}
    >
      <Markdown remarkPlugins={[remarkGfm]}>{content}</Markdown>
    </div>
  );
}

/**
 * 单条流在主面板和弹窗详情里都要以相同方式呈现 output/thinking 双视图
 */
function StreamGroupDetail({
  group,
  maxLines,
  className,
  forceTabs = false,
  emptyOutputMessage = "暂无输出",
  emptyThinkingMessage = "暂无思考内容",
}: {
  group: LLMStreamGroup;
  maxLines: number;
  className?: string;
  forceTabs?: boolean;
  emptyOutputMessage?: string;
  emptyThinkingMessage?: string;
}) {
  const outputContent = useMemo(
    () => _limitMarkdownLines(group.outputText, maxLines),
    [group.outputText, maxLines],
  );
  const thinkingContent = useMemo(
    () => _limitMarkdownLines(group.thinkingText, maxLines),
    [group.thinkingText, maxLines],
  );
  const hasOutput = outputContent.trim().length > 0;
  const hasThinking = thinkingContent.trim().length > 0;
  const showTabs = forceTabs || hasThinking;
  const resolvedOutputContent = hasOutput ? outputContent : emptyOutputMessage;
  const resolvedThinkingContent = hasThinking ? thinkingContent : emptyThinkingMessage;

  if (!showTabs) {
    return <StreamMarkdownPanel content={resolvedOutputContent} className={className} />;
  }

  return (
    <Tabs defaultValue="output" className={cn("flex h-full flex-col", className)}>
      <TabsList className="mb-3 shrink-0 self-start">
        <TabsTrigger value="output">输出</TabsTrigger>
        <TabsTrigger value="thinking">思考</TabsTrigger>
      </TabsList>
      <TabsContent value="output" className="mt-0 min-h-0 flex-1">
        <StreamMarkdownPanel content={resolvedOutputContent} className="h-full" />
      </TabsContent>
      <TabsContent value="thinking" className="mt-0 min-h-0 flex-1">
        <StreamMarkdownPanel content={resolvedThinkingContent} className="h-full" />
      </TabsContent>
    </Tabs>
  );
}

export function StreamOutput({
  taskId,
  maxLines = 200,
  className,
}: StreamOutputProps) {
  const llmOutputs = useStreamStore((state) => state.llmOutputs);
  const activeStreamSelections = useStreamStore((state) => state.activeStreamSelections);
  const progress = useStreamStore((state) => state.progress);
  const currentTaskId = useStreamStore((state) => state.currentTaskId);
  const setActiveStreamSelection = useStreamStore((state) => state.setActiveStreamSelection);
  const [isDialogOpen, setIsDialogOpen] = useState(false);
  const shouldStabilizePhaseTabs = progress?.stage === "annotate"
    && ANNOTATION_PHASE_TAB_SUBSTAGES.has(progress.sub_stage || "");

  const currentScopeKey = useMemo(() => {
    if (!progress) {
      return null;
    }
    return buildLLMOutputScopeKey({
      stage: progress.stage,
      chunk_id: progress.chunk_id ?? 0,
      sub_stage: progress.sub_stage,
    });
  }, [progress]);

  const scopedGroups = useMemo(() => {
    if (!currentScopeKey) {
      return [];
    }
    return Array.from(llmOutputs.values()).filter((group) => {
      const groupScopeKey = buildLLMOutputScopeKey({
        stage: group.stage,
        chunk_id: group.chunkId,
        sub_stage: group.subStage,
      });
      return groupScopeKey === currentScopeKey;
    });
  }, [currentScopeKey, llmOutputs]);
  const chunkFallbackGroups = useMemo(() => {
    if (!progress || progress.stage !== "annotate") {
      return [];
    }
    const currentChunkId = progress.chunk_id ?? 0;
    return Array.from(llmOutputs.values()).filter((group) =>
      _isSameChunkScope(group, progress.stage, currentChunkId),
    );
  }, [llmOutputs, progress]);
  const visibleGroups = useMemo(() => {
    if (scopedGroups.length > 0) {
      return scopedGroups;
    }
    if (shouldStabilizePhaseTabs) {
      return chunkFallbackGroups;
    }
    return scopedGroups;
  }, [chunkFallbackGroups, scopedGroups, shouldStabilizePhaseTabs]);

  const streamNumberByGroupKey = useMemo(() => {
    return new Map(visibleGroups.map((group, index) => [group.groupKey, index + 1]));
  }, [visibleGroups]);

  const latestGroupKey = useMemo(() => {
    let latestGroup: LLMStreamGroup | null = null;
    for (const group of visibleGroups) {
      if (!latestGroup || group.lastUpdatedAt >= latestGroup.lastUpdatedAt) {
        latestGroup = group;
      }
    }
    return latestGroup?.groupKey ?? null;
  }, [visibleGroups]);

  const activeGroup = useMemo(() => {
    if (!currentScopeKey) {
      return null;
    }
    const activeGroupKey = activeStreamSelections.get(currentScopeKey);
    return (
      visibleGroups.find((group) => group.groupKey === activeGroupKey)
      ?? visibleGroups.find((group) => group.groupKey === latestGroupKey)
      ?? null
    );
  }, [activeStreamSelections, currentScopeKey, latestGroupKey, visibleGroups]);
  const hasMixedVisibleSubStages = useMemo(() => {
    if (visibleGroups.length <= 1) {
      return false;
    }
    const firstSubStage = visibleGroups[0]?.subStage ?? "";
    return visibleGroups.some((group) => group.subStage !== firstSubStage);
  }, [visibleGroups]);
  const isChunkFallbackMode = shouldStabilizePhaseTabs && scopedGroups.length === 0 && visibleGroups.length > 0;
  const displayGroup = useMemo(() => {
    if (!activeGroup) {
      return null;
    }
    if (!isChunkFallbackMode || !progress) {
      return activeGroup;
    }

    const latestOutputGroup = _pickLatestGroupWithContent(visibleGroups, "output");
    const latestThinkingGroup = _pickLatestGroupWithContent(visibleGroups, "thinking");

    if (!latestOutputGroup && !latestThinkingGroup) {
      return activeGroup;
    }

    return {
      ...activeGroup,
      groupKey: `fallback-display-${currentScopeKey ?? activeGroup.groupKey}`,
      stage: progress.stage,
      subStage: progress.sub_stage,
      chunkId: progress.chunk_id ?? activeGroup.chunkId,
      outputText: latestOutputGroup?.outputText ?? activeGroup.outputText,
      outputTotalChars: latestOutputGroup?.outputTotalChars ?? activeGroup.outputTotalChars,
      thinkingText: latestThinkingGroup?.thinkingText ?? activeGroup.thinkingText,
      thinkingTotalChars: latestThinkingGroup?.thinkingTotalChars ?? activeGroup.thinkingTotalChars,
      lastUpdatedAt: Math.max(
        latestOutputGroup?.lastUpdatedAt ?? 0,
        latestThinkingGroup?.lastUpdatedAt ?? 0,
        activeGroup.lastUpdatedAt,
      ),
    };
  }, [activeGroup, currentScopeKey, isChunkFallbackMode, progress, visibleGroups]);

  if (!progress || currentTaskId !== taskId) return null;

  if (!activeGroup) {
    if (shouldStabilizePhaseTabs) {
      const pendingGroup: LLMStreamGroup = {
        groupKey: `pending-${currentScopeKey ?? "default"}`,
        stage: progress.stage,
        subStage: progress.sub_stage,
        chunkId: progress.chunk_id ?? 0,
        streamId: null,
        outputText: "",
        thinkingText: "",
        outputTotalChars: 0,
        thinkingTotalChars: 0,
        lastUpdatedAt: 0,
      };

      return (
        <AnimatePresence mode="wait">
          <motion.div
            key="stream-output-pending"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            transition={{ duration: 0.3, ease: "easeOut" }}
            className={cn("flex h-full min-h-0 flex-col gap-3", className)}
            aria-label="LLM 输出内容"
            aria-live="polite"
            aria-atomic="false"
          >
            <div className="shrink-0 rounded-lg border border-border bg-surface-secondary p-4 text-sm text-text-muted">
              <div className="mb-2 flex items-center gap-2">
                <div className="h-2 w-2 animate-pulse rounded-full bg-primary" />
                <span>正在执行 {STAGE_LABELS[progress.stage] || progress.stage}</span>
              </div>
              {progress.message && (
                <p className="text-xs text-text-muted">{progress.message}</p>
              )}
            </div>

            <div className="min-h-0 flex-1">
              <StreamGroupDetail
                group={pendingGroup}
                maxLines={maxLines}
                className="h-full"
                forceTabs
                emptyOutputMessage="模型输出尚未到达，面板会在收到首段输出后继续填充。"
                emptyThinkingMessage="模型思考尚未到达；若当前 provider 不返回 thinking，这里会保持为空。"
              />
            </div>
          </motion.div>
        </AnimatePresence>
      );
    }

    return (
      <div
        className={cn(
          "rounded-lg border border-border bg-surface-secondary p-4",
          "text-sm text-text-muted",
          className,
        )}
      >
        <div className="mb-2 flex items-center gap-2">
          <div className="h-2 w-2 animate-pulse rounded-full bg-primary" />
          <span>正在执行 {STAGE_LABELS[progress.stage] || progress.stage}</span>
        </div>
        {progress.message && (
          <p className="text-xs text-text-muted">{progress.message}</p>
        )}
        <p className="mt-2 text-xs text-text-muted">
          LLM 输出将在模型推理阶段显示...
        </p>
      </div>
    );
  }

  const activeStreamNumber = streamNumberByGroupKey.get(activeGroup.groupKey) ?? 1;
  const latestStreamNumber = latestGroupKey ? (streamNumberByGroupKey.get(latestGroupKey) ?? null) : null;
  const showMultiStreamSummary = visibleGroups.length > 1 && !hasMixedVisibleSubStages;

  return (
    <AnimatePresence mode="wait">
      <motion.div
        key="stream-output"
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -10 }}
        transition={{ duration: 0.3, ease: "easeOut" }}
        className={cn("flex h-full min-h-0 flex-col gap-3", className)}
        aria-label="LLM 输出内容"
        aria-live="polite"
        aria-atomic="false"
      >
        {showMultiStreamSummary && (
          <div className="shrink-0 rounded-lg border border-border bg-surface-secondary p-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="text-sm text-text-secondary">
                并行 {visibleGroups.length} 条流，当前查看：{_buildStreamLabel(activeStreamNumber)}
              </div>
              <Button variant="outline" size="sm" onClick={() => setIsDialogOpen(true)}>
                查看全部流
              </Button>
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              {visibleGroups.map((group) => {
                const streamNumber = streamNumberByGroupKey.get(group.groupKey) ?? 1;
                const isActive = group.groupKey === activeGroup.groupKey;
                const isLatest = group.groupKey === latestGroupKey;
                return (
                  <button
                    key={group.groupKey}
                    type="button"
                    onClick={() => currentScopeKey && setActiveStreamSelection(currentScopeKey, group.groupKey)}
                    className={cn(
                      "rounded-full border px-3 py-1 text-xs transition-colors",
                      isActive
                        ? "border-primary bg-primary/10 text-primary"
                        : "border-border bg-surface text-text-secondary hover:border-primary/40",
                    )}
                  >
                    {_buildStreamLabel(streamNumber)}
                    {isLatest && latestStreamNumber !== null ? " · 最近更新" : ""}
                  </button>
                );
              })}
            </div>
          </div>
        )}

        <div className="min-h-0 flex-1">
          <StreamGroupDetail
            group={displayGroup ?? activeGroup}
            maxLines={maxLines}
            className="h-full"
            forceTabs={shouldStabilizePhaseTabs}
            emptyOutputMessage="模型输出尚未到达，面板会在收到首段输出后继续填充。"
            emptyThinkingMessage="模型思考尚未到达；若当前 provider 不返回 thinking，这里会保持为空。"
          />
        </div>

        <Dialog open={isDialogOpen} onOpenChange={setIsDialogOpen}>
          <DialogContent className="max-h-[80vh] max-w-5xl overflow-hidden p-0">
            <DialogHeader className="border-b border-border p-6 pb-4">
              <DialogTitle>Phase3 多流输出</DialogTitle>
              <DialogDescription>
                当前 chunk 的并行推理流会按独立 stream 分组展示，避免不同 batch 文本继续混流。
              </DialogDescription>
            </DialogHeader>
            <div className="grid h-[70vh] min-h-0 grid-cols-1 gap-0 md:grid-cols-[280px_minmax(0,1fr)]">
              <div className="border-b border-border p-4 md:border-b-0 md:border-r">
                <div className="h-full overflow-auto">
                  <div className="space-y-2">
                    {visibleGroups.map((group) => {
                      const streamNumber = streamNumberByGroupKey.get(group.groupKey) ?? 1;
                      const outputLength = group.outputTotalChars;
                      const isActive = group.groupKey === activeGroup.groupKey;
                      const isLatest = group.groupKey === latestGroupKey;
                      return (
                        <button
                          key={group.groupKey}
                          type="button"
                          onClick={() => currentScopeKey && setActiveStreamSelection(currentScopeKey, group.groupKey)}
                          className={cn(
                            "w-full rounded-lg border px-3 py-2 text-left transition-colors",
                            isActive
                              ? "border-primary bg-primary/10"
                              : "border-border bg-surface-secondary hover:border-primary/40",
                          )}
                        >
                          <div className="flex items-center justify-between gap-2">
                            <span className="text-sm font-medium text-text">
                              {_buildStreamLabel(streamNumber)}
                            </span>
                            {isLatest && (
                              <span className="text-[11px] text-primary">最近更新</span>
                            )}
                          </div>
                          <div className="mt-1 text-xs text-text-muted">
                            输出 {outputLength} 字
                          </div>
                        </button>
                      );
                    })}
                  </div>
                </div>
              </div>
              <div className="min-h-0 p-4">
                <StreamGroupDetail group={activeGroup} maxLines={maxLines} className="h-full" />
              </div>
            </div>
          </DialogContent>
        </Dialog>
      </motion.div>
    </AnimatePresence>
  );
}
