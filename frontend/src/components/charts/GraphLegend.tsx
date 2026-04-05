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
/*  Constants - 与 ForceGraph.tsx 保持一致的配色                       */
/* ------------------------------------------------------------------ */

/**
 * 实体类型显示名称和 Tailwind 色类
 * 注意：Canvas 渲染使用 HSL 硬编码值（Canvas API 限制），这里用近似的 Tailwind 类名展示
 */
const ENTITY_TYPE_CONFIG: Record<string, { label: string; colorClass: string }> = {
  character: { label: "角色", colorClass: "bg-[hsl(234,89%,55%)]" },
  group: { label: "群体", colorClass: "bg-[hsl(274,79%,55%)]" },
  organization: { label: "组织", colorClass: "bg-[hsl(194,79%,55%)]" },
  location: { label: "地点", colorClass: "bg-[hsl(314,74%,55%)]" },
  item: { label: "物品", colorClass: "bg-[hsl(154,74%,55%)]" },
  event: { label: "事件", colorClass: "bg-[hsl(234,10%,60%)]" },
  concept: { label: "概念", colorClass: "bg-[hsl(234,10%,40%)]" },
};

/**
 * 关系类型 Tailwind 色类（与 ForceGraph.RELATION_TYPE_COLORS 对应的近似色）
 */
const RELATION_TYPE_COLOR_MAP: Record<string, string> = {
  友好: "bg-[hsl(145,55%,48%)]",
  敌对: "bg-[hsl(0,65%,55%)]",
  从属: "bg-[hsl(234,10%,60%)]",
  合作: "bg-[hsl(274,79%,55%)]",
  亲情: "bg-[hsl(194,79%,55%)]",
  爱情: "bg-[hsl(314,74%,55%)]",
  师徒: "bg-[hsl(154,74%,55%)]",
};

/**
 * 层级关系类型集合（与 ForceGraph.HIERARCHICAL_RELATION_TYPES 一致）
 * 用于在图例中标注虚线/实线样式
 */
const HIERARCHICAL_TYPES = new Set(["从属", "师徒", "上下级", "隶属", "管理"]);

function getRelationColorClass(relationType: string): string {
  return RELATION_TYPE_COLOR_MAP[relationType] || "bg-[hsl(234,10%,60%)]";
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
              {entityTypes.map((type) => {
                const config = ENTITY_TYPE_CONFIG[type];
                return (
                  <div key={type} className="flex items-center gap-2">
                    <span
                      className={cn(
                        "h-2.5 w-2.5 rounded-full",
                        config?.colorClass || "bg-text-muted"
                      )}
                    />
                    <span className="text-sm text-text-secondary">
                      {config?.label || type}
                    </span>
                  </div>
                );
              })}
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
                      className={cn(
                        "h-0.5 w-5 rounded-full",
                        getRelationColorClass(type),
                        isHierarchical && "border-dashed"
                      )}
                      style={
                        isHierarchical
                          ? { backgroundImage: `repeating-linear-gradient(90deg, transparent, transparent 3px, currentColor 3px, currentColor 6px)` }
                          : undefined
                      }
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
