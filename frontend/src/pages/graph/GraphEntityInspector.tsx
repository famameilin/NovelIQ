import { useMemo, useState } from "react";

import { ChevronDown, ChevronRight, CircleUserRound, Link2, MapPin, Search } from "lucide-react";

import type { GraphNode } from "@/api/types";
import type {
  EntityRelationSummary,
  GraphRelationGroup,
  GraphRelationItem,
} from "@/components/charts/forceGraph/graphFocusModel";
import { AnalysisDetails } from "@/components/common/AnalysisDetails";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/cn";
import { formatAnalysisLabel } from "@/lib/analysisLabels";
import { formatEntityTypeLabel, formatRelationDirectionLabel } from "@/lib/graphLabels";

interface GraphEntityInspectorProps {
  node: GraphNode | null;
  relationSummary: EntityRelationSummary;
  onSelectEntity: (node: GraphNode) => void;
  className?: string;
}

const DEFAULT_OPEN_GROUP_COUNT = 3;
const GROUP_ITEM_LIMIT = 10;

const NARRATIVE_ROLE_DESCRIPTIONS: Record<string, string> = {
  主体: "发起动作",
  客体: "承受动作",
  发送者: "发出信息",
  接收者: "接收信息",
  帮助者: "提供协助",
  反对者: "造成阻碍",
  见证者: "在场见证",
};

function countLabel(group: GraphRelationGroup): string {
  return `${group.items.length} 条`;
}

/**
 * 按关系类型分组展示实体关系
 * 简要说明：默认展开条数最多的前几组，组内按支持次数排序并支持按名筛选
 */
function RelationGroups({
  groups,
  query,
  onSelectEntity,
}: {
  groups: GraphRelationGroup[];
  query: string;
  onSelectEntity: (node: GraphNode) => void;
}) {
  const normalizedQuery = query.trim().toLowerCase();
  const defaultOpen = useMemo(
    () => new Set(groups.slice(0, DEFAULT_OPEN_GROUP_COUNT).map((group) => group.relationType)),
    [groups],
  );
  const [openGroups, setOpenGroups] = useState<Set<string> | null>(null);
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());

  const effectiveOpen = openGroups ?? defaultOpen;
  const isSearching = normalizedQuery.length > 0;

  const toggleGroup = (relationType: string) => {
    const next = new Set(effectiveOpen);
    if (next.has(relationType)) {
      next.delete(relationType);
    } else {
      next.add(relationType);
    }
    setOpenGroups(next);
  };

  const toggleExpand = (relationType: string) => {
    const next = new Set(expandedGroups);
    if (next.has(relationType)) {
      next.delete(relationType);
    } else {
      next.add(relationType);
    }
    setExpandedGroups(next);
  };

  const visibleGroups = groups
    .map((group) => ({
      group,
      items: normalizedQuery
        ? group.items.filter((item) => item.node.name.toLowerCase().includes(normalizedQuery))
        : group.items,
    }))
    .filter((entry) => entry.items.length > 0);

  if (visibleGroups.length === 0) {
    return (
      <p className="mt-3 rounded-lg border border-dashed border-border/60 px-3 py-5 text-center text-sm text-text-muted">
        {isSearching ? "没有匹配的相关实体" : "暂无主要关系"}
      </p>
    );
  }

  return (
    <div className="mt-3 space-y-2">
      {visibleGroups.map(({ group, items }) => {
        const isOpen = isSearching || effectiveOpen.has(group.relationType);
        const isExpanded = isSearching || expandedGroups.has(group.relationType);
        const visibleItems = isExpanded ? items : items.slice(0, GROUP_ITEM_LIMIT);

        return (
          <div key={group.relationType} className="overflow-hidden rounded-lg border border-border/60">
            <button
              type="button"
              onClick={() => toggleGroup(group.relationType)}
              aria-expanded={isOpen}
              className="flex w-full items-center justify-between gap-3 bg-surface-hover/45 px-3 py-2 text-left transition-colors hover:bg-surface-hover"
            >
              <span className="flex min-w-0 items-center gap-2">
                {isOpen ? (
                  <ChevronDown className="h-3.5 w-3.5 shrink-0 text-text-muted" aria-hidden="true" />
                ) : (
                  <ChevronRight className="h-3.5 w-3.5 shrink-0 text-text-muted" aria-hidden="true" />
                )}
                <span className="truncate text-sm font-medium text-text">
                  {formatAnalysisLabel(group.relationType, "relation")}
                </span>
              </span>
              <span className="shrink-0 text-xs text-text-muted">{countLabel(group)}</span>
            </button>

            {isOpen ? (
              <div className="divide-y divide-border/50">
                {visibleItems.map((item) => (
                  <RelationItem
                    key={`${item.node.entity_id}-${item.relationType}`}
                    item={item}
                    onSelectEntity={onSelectEntity}
                  />
                ))}
                {!isExpanded && items.length > GROUP_ITEM_LIMIT ? (
                  <button
                    type="button"
                    onClick={() => toggleExpand(group.relationType)}
                    className="w-full px-3 py-2 text-left text-xs text-primary transition-colors hover:bg-surface-hover"
                  >
                    展开全部 {items.length} 条
                  </button>
                ) : null}
              </div>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

function RelationItem({
  item,
  onSelectEntity,
}: {
  item: GraphRelationItem;
  onSelectEntity: (node: GraphNode) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onSelectEntity(item.node)}
      className="flex w-full items-center justify-between gap-3 bg-background/40 px-3 py-2 text-left transition-colors hover:bg-surface-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/45"
    >
      <span className="min-w-0">
        <span className="block truncate text-sm font-medium text-text">{item.node.name}</span>
        <span className="mt-0.5 block text-xs text-text-muted">
          {formatRelationDirectionLabel(item.directionality)}
          {item.supportCount > 1 ? ` · 关联 ${item.supportCount} 次` : ""}
          {item.node.last_seen_chapter != null ? ` · 最后出现第 ${item.node.last_seen_chapter} 章` : ""}
        </span>
      </span>
      <Badge variant={item.isActive ? "secondary" : "outline"}>
        {item.isActive ? "当前有效" : "已经结束"}
      </Badge>
    </button>
  );
}

/**
 * 在关系画布旁展示用户可读的实体信息
 * 简要说明：隐藏内部编号，仅保留名称、出现范围、人物叙事作用、状态和分组关系
 */
export function GraphEntityInspector({
  node,
  relationSummary,
  onSelectEntity,
  className,
}: GraphEntityInspectorProps) {
  const [relationQuery, setRelationQuery] = useState("");

  if (!node) {
    return (
      <aside
        className={cn(
          "flex h-full min-h-0 items-center justify-center overflow-y-auto rounded-lg border border-dashed border-border/70 bg-surface/45 p-6 text-center",
          className,
        )}
      >
        <div className="max-w-xs">
          <CircleUserRound className="mx-auto h-8 w-8 text-text-muted/60" aria-hidden="true" />
          <h2 className="mt-3 text-sm font-medium text-text">选择一个实体</h2>
          <p className="mt-1 text-sm leading-6 text-text-muted">点击关系图中的节点，这里会显示其出现范围、主要关系和人物的叙事作用</p>
        </div>
      </aside>
    );
  }

  const narrativeRole = typeof node.state.role_function === "string" ? node.state.role_function.trim() : "";
  const roleDescription = NARRATIVE_ROLE_DESCRIPTIONS[narrativeRole];
  const stateStatus = typeof node.state.status === "string" ? node.state.status : null;
  const hasChapterRange = node.first_seen_chapter != null || node.last_seen_chapter != null;

  return (
    <aside className={cn("flex h-full min-h-0 flex-col overflow-y-auto rounded-lg border border-border/70 bg-surface/75 p-5", className)} aria-label={`${node.name}实体详情`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <CircleUserRound className="h-5 w-5 text-primary" aria-hidden="true" />
            <h2 className="truncate text-lg font-semibold text-text">{node.name}</h2>
          </div>
          <p className="mt-1 text-sm text-text-muted">{formatEntityTypeLabel(node.entity_type)}</p>
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
        {node.entity_type === "character" ? (
          <div className="rounded-lg bg-surface-hover/55 p-3">
            <dt className="text-xs text-text-muted">最近记录的叙事作用</dt>
            <dd className="mt-1 text-sm font-medium text-text">
              {narrativeRole
                ? `${narrativeRole}${roleDescription ? `（${roleDescription}）` : ""}`
                : "暂无叙事作用记录"}
            </dd>
          </div>
        ) : null}
      </dl>

      <section className="mt-5" aria-labelledby="graph-related-title">
        <div className="flex items-center justify-between gap-3">
          <h3 id="graph-related-title" className="flex items-center gap-2 text-sm font-medium text-text">
            <Link2 className="h-4 w-4 text-chart-2" aria-hidden="true" />
            主要关系
          </h3>
          <span className="text-xs text-text-muted" title={`原始关系 ${relationSummary.rawRelationCount} 条`}>
            {relationSummary.entityCount} 位 · {relationSummary.relationCount} 条
          </span>
        </div>

        {relationSummary.groups.length > 0 ? (
          <div className="relative mt-3">
            <Search className="pointer-events-none absolute left-2.5 top-2.5 h-3.5 w-3.5 text-text-muted" />
            <Input
              type="text"
              value={relationQuery}
              onChange={(event) => setRelationQuery(event.target.value)}
              placeholder="在这些关系中筛选名称..."
              className="h-8 pl-8 text-xs"
            />
          </div>
        ) : null}

        <RelationGroups groups={relationSummary.groups} query={relationQuery} onSelectEntity={onSelectEntity} />
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
