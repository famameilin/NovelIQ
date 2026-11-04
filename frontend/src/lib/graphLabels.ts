/** 图谱实体的中文名称 */
export const ENTITY_TYPE_LABELS: Record<string, string> = {
  character: "人物",
  location: "地点",
  item: "物品",
  organization: "组织",
  group: "群体",
};

/** 图谱实体类型的兜底名称 */
export function formatEntityTypeLabel(entityType: string): string {
  return ENTITY_TYPE_LABELS[entityType] ?? "其他实体";
}

/** 关系方向的展示文案 */
export function formatRelationDirectionLabel(
  directionality?: "directed" | "bidirectional" | null,
): string {
  if (directionality === "bidirectional") return "双向关系";
  if (directionality === "directed") return "单向关系";
  return "方向未标注";
}
