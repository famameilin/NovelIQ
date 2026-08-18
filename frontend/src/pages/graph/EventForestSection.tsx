/**
 * 事件森林/DAG 过程视图组件
 *
 * 2026-08-18 P2：展示事件节点、因果边和伏笔边，复用现有章节/图版本选择能力。
 */

import { useQuery } from "@tanstack/react-query";

import { getEventForest } from "@/api/results";
import type { EventForestResponse } from "@/api/types";
import { AnalysisWorkspace } from "@/components/layout/AnalysisWorkspace";

interface EventForestSectionProps {
  novelId: string;
  taskId: string;
  chapterId?: number;
  graphVersionId?: string;
}

/**
 * 2026-08-18 用于按章节边界渲染事件节点列表、因果边和伏笔边
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

function EventForestContent({ data }: { data: EventForestResponse }) {
  const nodesByChapter = new Map<number, typeof data.event_nodes>();
  for (const node of data.event_nodes) {
    const list = nodesByChapter.get(node.chapter_id) ?? [];
    list.push(node);
    nodesByChapter.set(node.chapter_id, list);
  }

  const causalEdges = data.event_edges.filter((e) => e.edge_type === "causal");
  const activeForeshadowing = data.foreshadowing_edges.filter((e) => e.active);
  const resolvedForeshadowing = data.foreshadowing_edges.filter((e) => !e.active);

  const participantLabel = (participant: Record<string, unknown>): string => {
    const entity = participant.entity;
    if (typeof entity === "string") return entity;
    if (entity && typeof entity === "object") {
      const record = entity as Record<string, unknown>;
      return String(record.name ?? record.canonical_name ?? "?");
    }
    return String(participant.name ?? "?");
  };

  return (
    <div className="h-full overflow-auto p-4 space-y-6">
      <div className="text-sm text-text-muted">
        截止第 {data.chapter_order} 章边界 · {data.event_nodes.length} 个事件 ·{" "}
        {causalEdges.length} 条因果边 · {data.foreshadowing_edges.length} 条伏笔边
      </div>

      <section>
        <h3 className="mb-2 text-base font-semibold text-text">事件节点</h3>
        <div className="space-y-3">
          {Array.from(nodesByChapter.entries()).map(([chapterId, nodes]) => (
            <div key={chapterId} className="rounded-lg border border-border p-3">
              <div className="mb-2 text-xs font-medium text-text-muted">
                第 {chapterId} 章（{nodes.length} 个事件）
              </div>
              <div className="space-y-2">
                {nodes.map((node) => (
                  <div key={node.event_id} className="rounded border border-border bg-surface p-2">
                    <div className="text-sm text-text">{node.description}</div>
                    <div className="mt-1 flex flex-wrap gap-2 text-xs text-text-muted">
                      {node.participants.map((p, i) => (
                        <span key={i} className="rounded bg-surface-hover px-1.5 py-0.5">
                          {String(p.role)}: {participantLabel(p)}
                        </span>
                      ))}
                      {node.causal_event_refs.length > 0 && (
                        <span className="rounded bg-surface-hover px-1.5 py-0.5">
                          因果前驱: {node.causal_event_refs.join(", ")}
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </section>

      {activeForeshadowing.length > 0 && (
        <section>
          <h3 className="mb-2 text-base font-semibold text-text">活跃伏笔</h3>
          <div className="space-y-2">
            {activeForeshadowing.map((fe) => (
              <div
                key={fe.setup_id}
                className="rounded-lg border border-border p-3"
              >
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
              <div
                key={fe.setup_id}
                className="rounded-lg border border-border p-3 opacity-60"
              >
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
