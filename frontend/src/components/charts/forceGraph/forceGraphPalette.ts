import { getCSSColorVar } from "@/lib/theme";

export interface EntityColors {
  character: string;
  group: string;
  organization: string;
  location: string;
  item: string;
  event: string;
  concept: string;
}

export interface RelationColors {
  [key: string]: string;
}

export interface AuxColors {
  background: string;
  text: string;
  neutral: string;
  positive: string;
  negative: string;
}

export interface ForceGraphPalette {
  entityColors: EntityColors;
  relationColors: RelationColors;
  auxColors: AuxColors;
}

// 2026-04-23，任务：复杂度与耦合审查 P1
// 把图谱配色提取成独立模块，避免 ForceGraph 同时维护生命周期和颜色映射。
function getEntityColorsFromCSS(): EntityColors {
  return {
    character: getCSSColorVar("--primary"),
    group: getCSSColorVar("--chart-2"),
    organization: getCSSColorVar("--chart-3"),
    location: getCSSColorVar("--chart-4"),
    item: getCSSColorVar("--chart-5"),
    event: getCSSColorVar("--chart-neutral"),
    concept: getCSSColorVar("--chart-neutral"),
  };
}

// 2026-04-23，任务：复杂度与耦合审查 P1
// 统一关系类型颜色来源，保证图例和图谱主图后续可以复用同一套调色规则。
function getRelationColorsFromCSS(): RelationColors {
  return {
    友好: getCSSColorVar("--chart-positive"),
    亲情: getCSSColorVar("--chart-positive"),
    爱情: getCSSColorVar("--chart-positive"),
    爱慕: getCSSColorVar("--chart-positive"),
    敌对: getCSSColorVar("--chart-negative"),
    仇恨: getCSSColorVar("--chart-negative"),
    从属: getCSSColorVar("--chart-neutral"),
    师徒: getCSSColorVar("--chart-neutral"),
    家族: getCSSColorVar("--chart-neutral"),
  };
}

// 2026-04-23，任务：复杂度与耦合审查 P1
// 收口辅助色，避免 ForceGraph 在多个闭包里重复读取 CSS 变量。
function getAuxColorsFromCSS(): AuxColors {
  return {
    background: getCSSColorVar("--background"),
    text: getCSSColorVar("--text"),
    neutral: getCSSColorVar("--chart-neutral"),
    positive: getCSSColorVar("--chart-positive"),
    negative: getCSSColorVar("--chart-negative"),
  };
}

// 2026-04-23，任务：复杂度与耦合审查 P1
// 给 G6 生命周期 hook 提供单一 palette 输入，减少跨文件参数噪声。
export function createForceGraphPalette(): ForceGraphPalette {
  return {
    entityColors: getEntityColorsFromCSS(),
    relationColors: getRelationColorsFromCSS(),
    auxColors: getAuxColorsFromCSS(),
  };
}
