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
import {
  buildLLMOutputScopeKey,
  type LLMStreamGroup,
  type StreamBlock,
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

/**
 * 2026-08-12: 标注阶段 agent 化后，后端 sub_stage 固定为 chapter_agent（不再下发 phase1-4）。
 * 该集合仅用于判定标注 Agent 运行期是否启用"同 chunk 回退 + pending 骨架"的稳定化逻辑；
 * chunkFallbackGroups / pendingGroup / displayGroup 回退链在单枚举值下基本不再触发，
 * 保留它们以兜住"进度先到、流事件后到"的窗口期，避免阶段切换闪断。
 */
const ANNOTATION_PHASE_TAB_SUBSTAGES = new Set(["chapter_agent"]);

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

/** 工具调用状态徽标 */
function ToolStatusBadge({ status }: { status: "started" | "success" | "failed" }) {
  if (status === "started") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full border border-primary/30 bg-primary/10 px-2 py-0.5 text-[11px] text-primary">
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary" />
        进行中
      </span>
    );
  }
  if (status === "success") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-[11px] text-emerald-600">
        <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
        成功
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-red-500/30 bg-red-500/10 px-2 py-0.5 text-[11px] text-red-600">
      <span className="h-1.5 w-1.5 rounded-full bg-red-500" />
      失败
    </span>
  );
}

/**
 * "模型思考中"折叠块：内容为工具调用列表
 * 默认展开条件：该块是最后一块且其后还没有输出块（当前轮仍在思考）
 */
function ThinkingBlockCard({
  block,
  defaultExpanded,
}: {
  block: StreamBlock;
  defaultExpanded: boolean;
}) {
  const [manualExpanded, setManualExpanded] = useState<boolean | null>(null);
  const expanded = manualExpanded ?? defaultExpanded;
  const lastTool = block.tools[block.tools.length - 1];
  const hasTools = block.tools.length > 0;
  const statusText =
    !hasTools || lastTool.status === "started"
      ? "推理中"
      : lastTool.status === "success"
        ? "已完成"
        : "失败";

  return (
    <div className="shrink-0 rounded-lg border border-border bg-surface-secondary">
      <button
        type="button"
        onClick={() => setManualExpanded((prev) => (prev === null ? !defaultExpanded : !prev))}
        className="flex w-full items-center gap-2 px-3 py-2 text-left"
        aria-expanded={expanded}
      >
        <span
          className={cn(
            "text-xs text-text-muted transition-transform duration-200",
            expanded && "rotate-90",
          )}
        >
          ▶
        </span>
        <span className="text-sm font-medium text-text">模型思考中</span>
        <span
          className={cn(
            "ml-1 inline-flex items-center gap-1 text-[11px]",
            lastTool?.status === "failed"
              ? "text-red-600"
              : lastTool?.status === "success"
                ? "text-text-muted"
                : "text-primary",
          )}
        >
          {lastTool?.status === "started" || !hasTools ? (
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary" />
          ) : null}
          {statusText}
        </span>
      </button>
      {expanded && (
        <div className="border-t border-border px-3 py-2">
          {hasTools ? (
            <ul className="space-y-1.5">
              {block.tools.map((tool, index) => (
                <li key={`${tool.name}-${index}`} className="flex items-center justify-between gap-3">
                  <span className="truncate font-mono text-xs text-text-secondary">{tool.name}</span>
                  <ToolStatusBadge status={tool.status} />
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-xs text-text-muted">模型正在思考下一步动作…</p>
          )}
          {lastTool && lastTool.detail && lastTool.status !== "started" && (
            <p className="mt-2 line-clamp-3 text-[11px] text-text-muted">{lastTool.detail}</p>
          )}
        </div>
      )}
    </div>
  );
}

/** "模型输出"区块：模型文本 markdown */
function OutputBlockCard({ text, maxLines }: { text: string; maxLines: number }) {
  const content = _limitMarkdownLines(text, maxLines);
  return (
    <div className="shrink-0 rounded-lg border border-border bg-surface-secondary">
      <div className="border-b border-border px-3 py-2 text-sm font-medium text-text">
        模型输出
      </div>
      <div className="overflow-auto p-3">
        <div className="whitespace-pre-wrap break-words font-mono text-sm text-text-secondary">
          <Markdown remarkPlugins={[remarkGfm]}>{content}</Markdown>
        </div>
      </div>
    </div>
  );
}

/**
 * 单条流在主面板和弹窗详情里都以相同方式呈现顺序区块：
 * "模型思考中"（可折叠，内容=工具调用）→ "模型输出"（模型文本）循环
 */
function StreamGroupDetail({
  group,
  maxLines,
  className,
  emptyOutputMessage = "暂无输出",
}: {
  group: LLMStreamGroup;
  maxLines: number;
  className?: string;
  emptyOutputMessage?: string;
}) {
  const blocks = group.blocks;
  const hasOutput = group.outputText.trim().length > 0;

  if (blocks.length === 0) {
    return (
      <StreamMarkdownPanel
        content={hasOutput ? _limitMarkdownLines(group.outputText, maxLines) : emptyOutputMessage}
        className={className}
      />
    );
  }

  return (
    <div className={cn("h-full min-h-0 space-y-3 overflow-y-auto pr-1", className)}>
      {blocks.map((block, index) => {
        const hasOutputAfter = blocks.slice(index + 1).some((item) => item.kind === "output");
        if (block.kind === "thinking") {
          return (
            <ThinkingBlockCard
              key={`thinking-${index}`}
              block={block}
              defaultExpanded={index === blocks.length - 1 && !hasOutputAfter}
            />
          );
        }
        return <OutputBlockCard key={`output-${index}`} text={block.text} maxLines={maxLines} />;
      })}
    </div>
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
        toolTotalChars: 0,
        blocks: [],
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
                emptyOutputMessage="模型输出尚未到达，面板会在收到首段输出后继续填充。"
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
            emptyOutputMessage="模型输出尚未到达，面板会在收到首段输出后继续填充。"
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
                {/* 2026-08-13 P2-8: 与主面板保持一致，Dialog 同样渲染 displayGroup
                    （chunk 回退模式下是合并了各流最新内容的聚合组），
                    避免弹窗与主面板内容不一致 */}
                <StreamGroupDetail group={displayGroup ?? activeGroup} maxLines={maxLines} className="h-full" />
              </div>            </div>
          </DialogContent>
        </Dialog>
      </motion.div>
    </AnimatePresence>
  );
}
