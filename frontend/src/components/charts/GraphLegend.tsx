/**
 * GraphLegend 组件
 *
 * 创建时间: 2026-04-05
 * 创建者: GLM-5
 * 任务: 创建图谱图例组件
 * 说明: 用于显示关系图谱中节点类型和关系类型的图例
 */

import { cn } from "@/lib/cn";

/* ------------------------------------------------------------------ */
/*  Types                                                             */
/* ------------------------------------------------------------------ */

export interface GraphLegendProps {
  className?: string;
}

/* ------------------------------------------------------------------ */
/*  Constants                                                         */
/* ------------------------------------------------------------------ */

const nodeTypes = [
  { key: "character", label: "角色", color: "bg-chart-1" },
  { key: "group", label: "群体", color: "bg-chart-2" },
  { key: "organization", label: "组织", color: "bg-chart-3" },
];

const relationTypes = [
  { key: "friendly", label: "友好", color: "bg-chart-positive" },
  { key: "hostile", label: "敌对", color: "bg-chart-negative" },
  { key: "subordinate", label: "从属", color: "bg-chart-neutral" },
];

/* ------------------------------------------------------------------ */
/*  Component                                                         */
/* ------------------------------------------------------------------ */

export function GraphLegend({ className }: GraphLegendProps) {
  return (
    <div
      className={cn(
        "w-48 rounded-lg border border-border/60 bg-surface/95 p-3 backdrop-blur-sm shadow-sm",
        className
      )}
    >
      <div className="space-y-4">
        <div>
          <h4 className="mb-2 text-xs font-medium text-text-muted">节点类型</h4>
          <div className="space-y-1.5">
            {nodeTypes.map((node) => (
              <div key={node.key} className="flex items-center gap-2">
                <span
                  className={cn("h-2.5 w-2.5 rounded-full", node.color)}
                />
                <span className="text-sm text-text-secondary">{node.label}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="h-px bg-border/60" />

        <div>
          <h4 className="mb-2 text-xs font-medium text-text-muted">关系类型</h4>
          <div className="space-y-1.5">
            {relationTypes.map((relation) => (
              <div key={relation.key} className="flex items-center gap-2">
                <span
                  className={cn("h-0.5 w-5 rounded-full", relation.color)}
                />
                <span className="text-sm text-text-secondary">{relation.label}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
