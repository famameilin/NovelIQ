/**
 * 事件森林「树内图外」过程视图组件（契约 v3）
 *
 * 2026-08-19 P3：展示事件树列表（树根/主链/次因分支）与跨树因果边、伏笔边。
 * 复用现有章节/图版本选择能力；树视图由 eventForestLayout 纯函数组装。
 */

import { useQuery } from "@tanstack/react-query";

import { getEventForest } from "@/api/results";
import type { EventForestResponse } from "@/api/types";
import { AnalysisWorkspace } from "@/components/layout/AnalysisWorkspace";

import { buildEventForestView } from "./eventForestLayout";

interface EventForestSectionProps {
  novelId: string;
  taskId: string;
  chapterId?: number;
  graphVersionId?: string;
}

/**
 * 2026-08-19 用于按事件树渲染事件节点、跨树因果边和伏笔边
 */
export function EventForestSection({
  novelId,
  taskId,
  chapterId,
  graphVersionId,
}: EventForestSectionProps) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["event-forest", novelId, taskId, chapterId, graphVersionId],
    queryFn: () =>
      getEventForest(novelId, taskId, {
        ...(chapterId != null ? { chapterId } : {}),
        ...(graphVersionId ? { graphVersionId } : {}),
      }),
    staleTime: 5 * 60 * 1000,
  });

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-text-muted">
        事件森林加载中…
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-text-muted">
        事件森林数据不可用
      </div>
    );
  }

  return <EventForestContent data={data} />;
}

function participantLabel(participant: Record<string, unknown>): string {
  const entity = participant.entity;
  if (typeof entity === "string") return entity;
  if (entity && typeof entity === "object") {
    const record = entity as Record<string, unknown>;
    return String(record.name ?? record.canonical_name ?? "?");
  }
  return String(participant.name ?? "?");
}

function EventBadge({ node }: { node: { cause_role: string } }) {
  const label = { root: "根", main: "主链", secondary: "次因" }[node.cause_role] ?? node.cause_role;
  const tone =
    node.cause_role === "root"
      ? "bg-primary/20 text-primary"
      : node.cause_role === "secondary"
        ? "bg-warning/20 text-warning"
        : "bg-surface-hover text-text-muted";
  return (
    <span className={`rounded px-1.5 py-0.5 text-xs ${tone}`}>{label}</span>
  );
}

function EventNodeLine({
  node,
  index,
}: {
  node: { description: string; participants: Array<Record<string, unknown>> };
  index?: number;
}) {
  return (
    <div className="rounded border border-border bg-surface p-2">
      <div className="text-sm text-text">
        {index != null ? <span className="mr-1 text-text-muted">#{index}</span> : null}
        {node.description}
      </div>
      {node.participants.length > 0 && (
        <div className="mt-1 flex flex-wrap gap-2 text-xs text-text-muted">
          {node.participants.map((participant, i) => (
            <span key={i} className="rounded bg-surface-hover px-1.5 py-0.5">
              {String(participant.role)}: {participantLabel(participant)}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function EventForestContent({ data }: { data: EventForestResponse }) {
  const view = buildEventForestView(data);
  const activeForeshadowing = data.foreshadowing_edges.filter((edge) => edge.active);
  const resolvedForeshadowing = data.foreshadowing_edges.filter((edge) => !edge.active);

  return (
    <div className="h-full overflow-auto p-4 space-y-6">
      <div className="text-sm text-text-muted">
        截止第 {data.chapter_order} 章边界 · {view.trees.length} 棵事件树 ·{" "}
        {data.causal_edges.length} 条因果边 · {data.foreshadowing_edges.length} 条伏笔边
      </div>

      <section className="space-y-3">
        <h3 className="mb-2 text-base font-semibold text-text">事件树</h3>
        {view.trees.length === 0 && (
          <div className="text-sm text-text-muted">暂无事件树</div>
        )}
        {view.trees.map((tree, treeIndex) => (
          <div key={tree.treeId} className="rounded-lg border border-border p-3">
            <div className="mb-2 flex flex-wrap items-center gap-2 text-xs font-medium text-text-muted">
              树 {treeIndex + 1}
              <span className="rounded bg-surface-hover px-1.5 py-0.5">{tree.chapterRange}</span>
              <span className="rounded bg-surface-hover px-1.5 py-0.5">
                {tree.mainChain.length + tree.secondaryGroups.reduce((acc, g) => acc + g.branch.length, 0)} 个事件
              </span>
            </div>

            <div className="mb-1 flex items-center gap-2">
              <EventBadge node={tree.root} />
              <span className="text-xs text-text-muted">根：</span>
              <EventNodeLine node={tree.root} />
            </div>

            {tree.mainChain.length > 1 && (
              <div className="mt-1 space-y-1">
                {tree.mainChain.slice(1).map((node, i) => (
                  <div key={node.event_id} className="flex items-start gap-2">
                    <EventBadge node={node} />
                    <EventNodeLine node={node} index={i + 2} />
                  </div>
                ))}
              </div>
            )}

            {tree.secondaryGroups.map((group) => (
              <div key={group.target.event_id} className="mt-2 rounded border border-dashed border-border p-2">
                <div className="mb-1 flex items-center gap-2 text-xs text-text-muted">
                  <EventBadge node={{ cause_role: "secondary" }} />
                  次因分支 → 挂靠 {group.target.description}
                </div>
                <div className="space-y-1">
                  {group.branch.map((node) => (
                    <EventNodeLine key={node.event_id} node={node} />
                  ))}
                </div>
              </div>
            ))}
          </div>
        ))}
      </section>

      {view.crossTreeEdges.length > 0 && (
        <section>
          <h3 className="mb-2 text-base font-semibold text-text">跨树因果关系</h3>
          <div className="space-y-2">
            {view.crossTreeEdges.map((edge) => (
              <div key={edge.edge_id} className="rounded-lg border border-border p-3 text-sm">
                <span className="text-text">
                  {view.nodesById.get(edge.source_event_id)?.description ?? edge.source_event_id}
                </span>
                <span className="mx-2 text-text-muted">→</span>
                <span className="text-text">
                  {view.nodesById.get(edge.target_event_id)?.description ?? edge.target_event_id}
                </span>
                <span className="ml-2 text-xs text-text-muted">
                  第 {edge.source_chapter_id} 章 → 第 {edge.target_chapter_id} 章
                </span>
              </div>
            ))}
          </div>
        </section>
      )}

      {activeForeshadowing.length > 0 && (
        <section>
          <h3 className="mb-2 text-base font-semibold text-text">活跃伏笔</h3>
          <div className="space-y-2">
            {activeForeshadowing.map((fe) => (
              <div key={fe.setup_id} className="rounded-lg border border-border p-3">
                <div className="flex items-center gap-2">
                  <span className="rounded bg-warning/20 px-1.5 py-0.5 text-xs text-warning">
                    {fe.status}
                  </span>
                  <span className="text-sm text-text">{fe.setup_summary}</span>
                </div>
                <div className="mt-1 text-xs text-text-muted">
                  第 {fe.first_chapter_id}–{fe.last_chapter_id} 章 · setup_event:{" "}
                  {fe.setup_event_id.slice(0, 8)}…
                  {fe.payoff_event_id ? ` · payoff: ${fe.payoff_event_id.slice(0, 8)}…` : ""}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {resolvedForeshadowing.length > 0 && (
        <section>
          <h3 className="mb-2 text-base font-semibold text-text">已回收伏笔</h3>
          <div className="space-y-2">
            {resolvedForeshadowing.map((fe) => (
              <div key={fe.setup_id} className="rounded-lg border border-border p-3 opacity-60">
                <div className="flex items-center gap-2">
                  <span className="rounded bg-success/20 px-1.5 py-0.5 text-xs text-success">
                    {fe.status}
                  </span>
                  <span className="text-sm text-text">{fe.setup_summary}</span>
                </div>
                <div className="mt-1 text-xs text-text-muted">
                  第 {fe.first_chapter_id}–{fe.last_chapter_id} 章
                </div>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

export function EventForestTab({
  novelId,
  taskId,
  chapterId,
  graphVersionId,
}: EventForestSectionProps) {
  return (
    <AnalysisWorkspace.Tab value="events" label="事件过程">
      <EventForestSection
        novelId={novelId}
        taskId={taskId}
        chapterId={chapterId}
        graphVersionId={graphVersionId}
      />
    </AnalysisWorkspace.Tab>
  );
}
