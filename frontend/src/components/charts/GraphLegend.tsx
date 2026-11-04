/**
 * GraphLegend 组件
 *
 * 以紧凑横向条渲染节点类型与关系类型图例，颜色取 CSS 变量与 ForceGraph 配色同步
 */

import { cn } from "@/lib/cn";
import { getCSSColorVar } from "@/lib/theme";
import { formatAnalysisLabel } from "@/lib/analysisLabels";
import { formatEntityTypeLabel } from "@/lib/graphLabels";

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
  if (entityTypes.length === 0 && relationTypes.length === 0) {
    return null;
  }

  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-x-4 gap-y-1.5 rounded-lg border border-border/60 bg-surface/70 px-3 py-2",
        className,
      )}
    >
      {entityTypes.length > 0 && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className="text-[11px] text-text-muted">节点</span>
          {entityTypes.map((type) => (
            <span key={type} className="flex items-center gap-1.5">
              <span
                className="h-2 w-2 rounded-full"
                style={{ backgroundColor: getEntityColor(type) }}
              />
              <span className="text-[11px] text-text-secondary">{formatEntityTypeLabel(type)}</span>
            </span>
          ))}
        </div>
      )}

      {relationTypes.length > 0 && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className="text-[11px] text-text-muted">关系</span>
          {relationTypes.map((type) => (
            <span key={type} className="flex items-center gap-1.5">
              <span
                className="h-0.5 w-4 rounded-full"
                style={{ backgroundColor: getRelationColor(type) }}
              />
              <span className="text-[11px] text-text-secondary">{formatAnalysisLabel(type, "relation")}</span>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

export default GraphLegend;
