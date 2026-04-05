/**
 * GraphLegend 组件
 *
 * 创建时间: 2026-04-05
 * 创建者: GLM-5
 * 任务: 创建图谱图例组件
 * 说明: 动态显示关系图谱中节点类型和关系类型的图例，从实际数据派生内容
 *
 * 修改时间: 2026-04-05
 * 修改者: Code Review Fix
 * 修改内容:
 *   - 重构为动态生成模式，根据传入的实际 entityTypes/relationTypes 数据渲染图例
 *   - 解决之前硬编码 3 种节点类型、3 种英文 key 关系类型的 bug
 *   - 颜色映射与 ForceGraph.tsx 的 ENTITY_TYPE_COLORS / RELATION_TYPE_COLORS 保持一致
 *
 * 修改时间: 2026-04-05
 * 修改者: Theme Optimization
 * 修改内容:
 *   - 颜色从硬编码 HSL 改为 CSS 变量（使用 var(--xxx) 内联样式）
 *   - 与 ForceGraph 的"一书一色"主题系统完全同步
 */

import { cn } from "@/lib/cn";

/* ------------------------------------------------------------------ */
/*  Types                                                             */
/* ------------------------------------------------------------------ */

export interface GraphLegendProps {
  /** 当前图谱中实际存在的实体类型列表（从数据中提取） */
  entityTypes?: string[];
  /** 当前图谱中实际存在的关系类型列表（从数据中提取） */
  relationTypes?: string[];
  className?: string;
}

/* ------------------------------------------------------------------ */
/*  Constants - 使用 CSS 变量，跟随"一书一色"主题                       */
/* ------------------------------------------------------------------ */

/** 实体类型 → CSS 变量名映射（与 ForceGraph.getEntityColorsFromCSS 一致） */
const ENTITY_CSS_VARS: Record<string, string> = {
  character: "var(--primary)",
  group: "var(--chart-2)",
  organization: "var(--chart-3)",
  location: "var(--chart-4)",
  item: "var(--chart-5)",
  event: "var(--chart-neutral)",
  concept: "var(--chart-neutral)",
};

/** 实体类型显示名称 */
const ENTITY_LABELS: Record<string, string> = {
  character: "角色",
  group: "群体",
  organization: "组织",
  location: "地点",
  item: "物品",
  event: "事件",
  concept: "概念",
};

/** 关系类型 → CSS 变量名映射（与 ForceGraph.getRelationColorsFromCSS 一致） */
const RELATION_CSS_VARS: Record<string, string> = {
  "友好": "var(--chart-positive)",
  "敌对": "var(--chart-negative)",
  "从属": "var(--chart-neutral)",
  "合作": "var(--chart-2)",
  "亲情": "var(--chart-positive)",
  "爱情": "var(--chart-4)",
  "师徒": "var(--chart-5)",
};

/** 层级关系类型集合（与 ForceGraph.HIERARCHICAL_RELATION_TYPES 一致） */
const HIERARCHICAL_TYPES = new Set(["从属", "师徒", "上下级", "隶属", "管理"]);

function getEntityCssVar(entityType: string): string {
  return ENTITY_CSS_VARS[entityType] || "var(--chart-neutral)";
}

function getRelationCssVar(relationType: string): string {
  return RELATION_CSS_VARS[relationType] || "var(--chart-neutral)";
}

/* ------------------------------------------------------------------ */
/*  Component                                                         */
/* ------------------------------------------------------------------ */

export function GraphLegend({
  entityTypes = [],
  relationTypes = [],
  className,
}: GraphLegendProps) {
  // 如果没有数据传入，不渲染任何内容
  if (entityTypes.length === 0 && relationTypes.length === 0) {
    return null;
  }

  return (
    <div
      className={cn(
        "w-48 rounded-lg border border-border/60 bg-surface/95 p-3 backdrop-blur-sm shadow-sm",
        className
      )}
    >
      <div className="space-y-4">
        {/* 节点类型图例 */}
        {entityTypes.length > 0 && (
          <div>
            <h4 className="mb-2 text-xs font-medium text-text-muted">节点类型</h4>
            <div className="space-y-1.5">
              {entityTypes.map((type) => (
                <div key={type} className="flex items-center gap-2">
                  <span
                    className="h-2.5 w-2.5 rounded-full"
                    style={{ backgroundColor: getEntityCssVar(type) }}
                  />
                  <span className="text-sm text-text-secondary">
                    {ENTITY_LABELS[type] || type}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* 分隔线 */}
        {entityTypes.length > 0 && relationTypes.length > 0 && (
          <div className="h-px bg-border/60" />
        )}

        {/* 关系类型图例 */}
        {relationTypes.length > 0 && (
          <div>
            <h4 className="mb-2 text-xs font-medium text-text-muted">关系类型</h4>
            <div className="space-y-1.5">
              {relationTypes.map((type) => {
                const isHierarchical = HIERARCHICAL_TYPES.has(type);
                return (
                  <div key={type} className="flex items-center gap-2">
                    {/* 线条样式指示器：虚线或实线 */}
                    <span
                      className="h-0.5 w-5 rounded-full"
                      style={{
                        backgroundColor: getRelationCssVar(type),
                        ...(isHierarchical && {
                          backgroundImage: `repeating-linear-gradient(90deg, transparent, transparent 3px, currentColor 3px, currentColor 6px)`,
                        }),
                      }}
                    />
                    <span className="text-sm text-text-secondary">{type}</span>
                  </div>
                );
              })}
            </div>

            {/* 样式说明 */}
            <div className="mt-2 space-y-1 border-t border-border/40 pt-2">
              <div className="flex items-center gap-2">
                <span className="h-px w-5 bg-text-muted/50" />
                <span className="text-[10px] text-text-muted">动态关系（实线）</span>
              </div>
              <div className="flex items-center gap-2">
                <span
                  className="h-px w-5 bg-text-muted/50"
                  style={{
                    backgroundImage:
                      "repeating-linear-gradient(90deg, transparent, transparent 3px, currentColor 3px, currentColor 6px)",
                  }}
                />
                <span className="text-[10px] text-text-muted">层级关系（虚线）</span>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default GraphLegend;
