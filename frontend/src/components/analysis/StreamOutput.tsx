/** 按真实 Agent 和模型流展示通信内容 */
import { useEffect, useMemo, useRef, useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useStreamStore, type LLMStreamGroup, type StreamBlock } from "@/store/streamStore";
import { cn } from "@/lib/cn";
export interface StreamOutputProps {taskId: string; maxLines?: number; className?: string;}
function _limitMarkdownLines(content: string, maxLines: number): string {
  const allLines = content.split("\n");
  return allLines.slice(-maxLines).join("\n");
}

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

export function StreamOutput({taskId, maxLines=200, className}: StreamOutputProps) {
  const outputs = useStreamStore((state) => state.llmOutputs);
  const currentTask = useStreamStore((state) => state.currentTaskId);
  const selection = useStreamStore((state) => state.activeStreamSelections.get(taskId));
  const select = useStreamStore((state) => state.setActiveStreamSelection);
  const groups = useMemo(() => Array.from(outputs.values()), [outputs]);
  const group = groups.find((item) => item.groupKey === selection) ?? groups.at(-1);
  if (currentTask !== taskId) return null;
  return <div className={cn("flex h-full min-h-0 flex-col gap-3", className)} aria-label="LLM 输出内容">
    {groups.length > 1 && <div className="flex shrink-0 flex-wrap gap-2">{groups.map((item, index) =>
      <button key={item.groupKey} type="button" onClick={() => select(taskId, item.groupKey)}
        className={cn("rounded-full border px-3 py-1 text-xs", item === group ? "border-primary text-primary" : "border-border text-text-muted")}>
        {item.agentType || "Agent"} · 流 {index+1}
      </button>)}</div>}
    <div className="min-h-0 flex-1">{group
      ? <StreamGroupDetail group={group} maxLines={maxLines} className="h-full" />
      : <p className="text-sm text-text-muted">等待模型输出</p>}</div>
  </div>;
}
