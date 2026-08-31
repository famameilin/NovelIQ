import { CircleUserRound, Link2, MapPin } from "lucide-react";

import type { GraphNode } from "@/api/types";
import { AnalysisDetails } from "@/components/common/AnalysisDetails";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/cn";
import { formatAnalysisLabel } from "@/lib/analysisLabels";

export interface GraphRelatedEntity {
  node: GraphNode;
  relationType: string;
  directionality: "directed" | "bidirectional";
  isActive: boolean;
}

interface GraphEntityInspectorProps {
  node: GraphNode | null;
  relatedEntities: GraphRelatedEntity[];
  onSelectEntity: (node: GraphNode) => void;
  className?: string;
}

const ENTITY_TYPE_LABELS: Record<string, string> = {
  character: "人物",
  location: "地点",
  item: "物品",
  organization: "组织",
};

/**
 * 2026-08-31，作用：将图谱实体类型转换为中文展示名称
 * 简要说明：未知类型使用通用实体名称，避免直接暴露内部枚举
 */
function getEntityTypeLabel(entityType: string): string {
  return ENTITY_TYPE_LABELS[entityType] ?? "其他实体";
}

/**
 * 2026-08-31，作用：将关系方向转换为中文展示名称
 * 简要说明：统一图谱详情和关系变化中的方向语义
 */
function getDirectionLabel(directionality: GraphRelatedEntity["directionality"]): string {
  return directionality === "bidirectional" ? "双向关系" : "单向关系";
}

/**
 * 2026-08-31，作用：在关系画布旁展示用户可读的实体信息
 * 简要说明：隐藏内部编号，仅保留名称、出现范围、职责、状态和主要关系
 */
export function GraphEntityInspector({
  node,
  relatedEntities,
  onSelectEntity,
  className,
}: GraphEntityInspectorProps) {
  if (!node) {
    return (
      <aside
        className={cn(
          "flex min-h-[320px] items-center justify-center rounded-lg border border-dashed border-border/70 bg-surface/45 p-6 text-center",
          className,
        )}
      >
        <div className="max-w-xs">
          <CircleUserRound className="mx-auto h-8 w-8 text-text-muted/60" aria-hidden="true" />
          <h2 className="mt-3 text-sm font-medium text-text">选择一个实体</h2>
          <p className="mt-1 text-sm leading-6 text-text-muted">点击关系图中的节点，这里会显示其出现范围、当前职责和主要关系</p>
        </div>
      </aside>
    );
  }

  const primaryRole =
    typeof node.state.primary_role_function === "string" ? node.state.primary_role_function : null;
  const stateStatus = typeof node.state.status === "string" ? node.state.status : null;
  const hasChapterRange = node.first_seen_chapter != null || node.last_seen_chapter != null;

  return (
    <aside className={cn("rounded-lg border border-border/70 bg-surface/75 p-5", className)} aria-label={`${node.name}实体详情`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <CircleUserRound className="h-5 w-5 text-primary" aria-hidden="true" />
            <h2 className="truncate text-lg font-semibold text-text">{node.name}</h2>
          </div>
          <p className="mt-1 text-sm text-text-muted">{getEntityTypeLabel(node.entity_type)}</p>
        </div>
        {stateStatus ? <Badge variant="secondary">{/^[\u4e00-\u9fff]/.test(stateStatus) ? stateStatus : "状态待确认"}</Badge> : null}
      </div>

      <dl className="mt-5 grid grid-cols-1 gap-3">
        <div className="rounded-lg bg-surface-hover/55 p-3">
          <dt className="flex items-center gap-1.5 text-xs text-text-muted">
            <MapPin className="h-3.5 w-3.5" aria-hidden="true" />
            出现范围
          </dt>
          <dd className="mt-1 text-sm font-medium text-text">
            {hasChapterRange
              ? `第 ${node.first_seen_chapter ?? "?"} 章至第 ${node.last_seen_chapter ?? "?"} 章`
              : "暂无章节范围"}
          </dd>
        </div>
        <div className="rounded-lg bg-surface-hover/55 p-3">
          <dt className="text-xs text-text-muted">当前职责</dt>
          <dd className="mt-1 text-sm font-medium text-text">
            {primaryRole ? formatAnalysisLabel(primaryRole, "role") : "暂无职责标注"}
          </dd>
        </div>
      </dl>

      <section className="mt-5" aria-labelledby="graph-related-title">
        <div className="flex items-center justify-between gap-3">
          <h3 id="graph-related-title" className="flex items-center gap-2 text-sm font-medium text-text">
            <Link2 className="h-4 w-4 text-chart-2" aria-hidden="true" />
            主要关系
          </h3>
          <span className="text-xs text-text-muted">{relatedEntities.length} 条</span>
        </div>
        {relatedEntities.length > 0 ? (
          <div className="mt-3 grid gap-2">
            {relatedEntities.map((relatedEntity) => (
              <button
                key={`${relatedEntity.node.entity_id}-${relatedEntity.relationType}`}
                type="button"
                onClick={() => onSelectEntity(relatedEntity.node)}
                className="flex w-full items-center justify-between gap-3 rounded-lg border border-border/60 bg-background/50 px-3 py-2.5 text-left transition-colors hover:bg-surface-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/45"
              >
                <span className="min-w-0">
                  <span className="block truncate text-sm font-medium text-text">{relatedEntity.node.name}</span>
                  <span className="mt-0.5 block text-xs text-text-muted">
                    {formatAnalysisLabel(relatedEntity.relationType, "relation")} · {getDirectionLabel(relatedEntity.directionality)}
                  </span>
                </span>
                <Badge variant={relatedEntity.isActive ? "secondary" : "outline"}>
                  {relatedEntity.isActive ? "当前有效" : "已经结束"}
                </Badge>
              </button>
            ))}
          </div>
        ) : (
          <p className="mt-3 rounded-lg border border-dashed border-border/60 px-3 py-5 text-center text-sm text-text-muted">暂无主要关系</p>
        )}
      </section>

      {(node.tags?.length || node.aliases?.length || node.state_chapter_id != null) ? (
        <AnalysisDetails className="mt-5" description="标签、别名与状态所在章节">
          <dl className="grid grid-cols-1 gap-3 text-sm">
            <div>
              <dt className="text-text-muted">标签</dt>
              <dd className="mt-1 text-text">{node.tags?.join("、") || "—"}</dd>
            </div>
            <div>
              <dt className="text-text-muted">别名</dt>
              <dd className="mt-1 text-text">{node.aliases?.join("、") || "—"}</dd>
            </div>
            <div>
              <dt className="text-text-muted">状态章节</dt>
              <dd className="mt-1 text-text">{node.state_chapter_id != null ? `第 ${node.state_chapter_id} 章` : "—"}</dd>
            </div>
          </dl>
        </AnalysisDetails>
      ) : null}
    </aside>
  );
}
