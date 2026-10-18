/**
 * GraphLegend 组件
 *
 * 按传入的 entityTypes/relationTypes 动态渲染节点类型与关系类型图例，
 * 颜色取 CSS 变量，与 ForceGraph 的配色主题同步
 */

import { cn } from "@/lib/cn";
import { getCSSColorVar } from "@/lib/theme";
import { formatAnalysisLabel } from "@/lib/analysisLabels";

/* ------------------------------------------------------------------ */
/*  类型定义                                                           */
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
const ENTITY_CSS_VAR_NAMES: Record<string, string> = {
  character: "--primary",
  group: "--chart-2",
  organization: "--chart-3",
  location: "--chart-4",
  item: "--chart-5",
};

/** 实体类型显示名称 */
const ENTITY_LABELS: Record<string, string> = {
  character: "角色",
  group: "群体",
  organization: "组织",
  location: "地点",
  item: "物品",
};

/** 关系类型 → CSS 变量名映射（与 ForceGraph.getRelationColorsFromCSS 一致） */
const RELATION_CSS_VAR_NAMES: Record<string, string> = {
  "家族": "--chart-neutral",
  "师徒": "--chart-neutral",
  "主从": "--chart-neutral",
  "敌对": "--chart-negative",
  "盟友": "--chart-positive",
  "友情": "--chart-positive",
  "爱慕": "--chart-positive",
  "利益": "--chart-neutral",
  "领导": "--chart-neutral",
  "同一人物": "--chart-neutral",
  "隶属": "--chart-neutral",
  "位于": "--chart-neutral",
};

function getEntityColor(entityType: string): string {
  const varName = ENTITY_CSS_VAR_NAMES[entityType];
  return varName ? getCSSColorVar(varName) : getCSSColorVar("--chart-neutral");
}

function getRelationColor(relationType: string): string {
  const varName = RELATION_CSS_VAR_NAMES[relationType];
  return varName ? getCSSColorVar(varName) : getCSSColorVar("--chart-neutral");
}

/* ------------------------------------------------------------------ */
/*  组件主体                                                           */
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
                    style={{ backgroundColor: getEntityColor(type) }}
                  />
                  <span className="text-sm text-text-secondary">
                    {ENTITY_LABELS[type] || formatAnalysisLabel(type, "entity")}
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
              {relationTypes.map((type) => (
                <div key={type} className="flex items-center gap-2">
                  <span
                    className="h-0.5 w-5 rounded-full"
                    style={{ backgroundColor: getRelationColor(type) }}
                  />
                  <span className="text-sm text-text-secondary">{formatAnalysisLabel(type, "relation")}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default GraphLegend;
