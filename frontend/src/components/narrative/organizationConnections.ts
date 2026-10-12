import type { NarrativeTreeResponse } from "@/api/narrativeTypes";

export interface OrganizationConnection { source_id: string; target_id: string; kinds: string[] }

/** 同一对端点只绘制一次，保留全部已保存关系类型用于图例和详情 */
export function organizationConnections(edges: NarrativeTreeResponse["edges"]): OrganizationConnection[] {
  const pairs = new Map<string, OrganizationConnection>();
  for (const edge of edges) {
    const key = `${edge.source_id}\0${edge.target_id}`;
    const pair = pairs.get(key) ?? { source_id: edge.source_id, target_id: edge.target_id, kinds: [] };
    if (!pair.kinds.includes(edge.kind)) pair.kinds.push(edge.kind);
    pairs.set(key, pair);
  }
  return [...pairs.values()];
}
