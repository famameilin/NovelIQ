import { describe, expect, it } from "vitest";

import type { GraphData, GraphEdge, GraphNode } from "@/api/types";

import {
  buildEntityRelationSummary,
  buildGraphSubgraph,
  countEntitiesByType,
  EGO_NEIGHBOR_LIMIT,
  rankGraphNodes,
  type GraphFocusOptions,
} from "./graphFocusModel";

function makeNode(
  id: string,
  name: string,
  entityType: GraphNode["entity_type"] = "character",
  extra: Partial<GraphNode> = {},
): GraphNode {
  return {
    entity_id: id,
    name,
    entity_type: entityType,
    first_seen_chapter: 1,
    last_seen_chapter: 1,
    state_chapter_id: 1,
    state: {},
    ...extra,
  };
}

function makeEdge(
  id: string,
  source: GraphNode,
  target: GraphNode,
  relationType = "盟友",
  supportCount = 1,
): GraphEdge {
  return {
    relation_id: id,
    state_chapter_id: 1,
    source_entity_id: source.entity_id,
    target_entity_id: target.entity_id,
    source_name: source.name,
    target_name: target.name,
    relation_type: relationType,
    directionality: "directed",
    relation_semantics: "ordinary",
    attributes: { support_count: supportCount },
    is_active: true,
    changes: [],
  };
}

function makeData(nodes: GraphNode[], edges: GraphEdge[]): GraphData {
  return { chapter_id: 1, chapter_order: 1, first_chapter_id: 1, last_chapter_id: 1, nodes, edges };
}

function options(overrides: Partial<GraphFocusOptions> = {}): GraphFocusOptions {
  return {
    scope: "core",
    entityTypes: new Set(["character"]),
    focusEntityId: null,
    relationTypes: new Set(),
    ...overrides,
  };
}

describe("buildGraphSubgraph", () => {
  it("默认只保留人物实体", () => {
    const hero = makeNode("c1", "顾霜");
    const city = makeNode("l1", "临安", "location");
    const data = makeData([hero, city], [makeEdge("e1", hero, city, "位于")]);

    const subgraph = buildGraphSubgraph(data, options());

    expect(subgraph.data.nodes.map((node) => node.entity_id)).toEqual(["c1"]);
    expect(subgraph.data.edges).toEqual([]);
    expect(subgraph.eligibleNodeCount).toBe(1);
    expect(subgraph.hiddenNodeCount).toBe(0);
  });

  it("核心范围只保留分数最高的节点与内部边", () => {
    const nodes = Array.from({ length: 40 }, (_, index) => makeNode(`c${index}`, `角色${index}`));
    const edges = nodes
      .slice(0, -1)
      .map((node, index) => makeEdge(`e${index}`, node, nodes[index + 1]));

    const subgraph = buildGraphSubgraph(makeData(nodes, edges), options({ scope: "core" }));

    expect(subgraph.data.nodes).toHaveLength(30);
    expect(subgraph.hiddenNodeCount).toBe(10);
    const visibleIds = new Set(subgraph.data.nodes.map((node) => node.entity_id));
    expect(
      subgraph.data.edges.every(
        (edge) => visibleIds.has(edge.source_entity_id) && visibleIds.has(edge.target_entity_id),
      ),
    ).toBe(true);
  });

  it("全部范围不裁剪节点", () => {
    const nodes = Array.from({ length: 40 }, (_, index) => makeNode(`c${index}`, `角色${index}`));
    const subgraph = buildGraphSubgraph(makeData(nodes, []), options({ scope: "all" }));

    expect(subgraph.data.nodes).toHaveLength(40);
    expect(subgraph.hiddenNodeCount).toBe(0);
  });

  it("聚焦模式只保留焦点与一跳邻居并截断邻居", () => {
    const focus = makeNode("c0", "中心");
    const neighbors = Array.from({ length: EGO_NEIGHBOR_LIMIT + 6 }, (_, index) =>
      makeNode(`c${index + 1}`, `邻居${index}`),
    );
    const edges = neighbors.map((node, index) => makeEdge(`e${index}`, focus, node, "盟友", index + 1));

    const subgraph = buildGraphSubgraph(
      makeData([focus, ...neighbors], edges),
      options({ focusEntityId: focus.entity_id }),
    );

    expect(subgraph.focusNode?.entity_id).toBe(focus.entity_id);
    expect(subgraph.data.nodes).toHaveLength(EGO_NEIGHBOR_LIMIT + 1);
    expect(subgraph.hiddenNodeCount).toBe(6);
    expect(subgraph.data.edges).toHaveLength(EGO_NEIGHBOR_LIMIT);
    expect(subgraph.data.nodes.some((node) => node.entity_id === focus.entity_id)).toBe(true);
  });

  it("聚焦模式不包含邻居之间的边", () => {
    const focus = makeNode("c0", "中心");
    const left = makeNode("c1", "甲");
    const right = makeNode("c2", "乙");
    const data = makeData(
      [focus, left, right],
      [makeEdge("e1", focus, left), makeEdge("e2", focus, right), makeEdge("e3", left, right, "敌对")],
    );

    const subgraph = buildGraphSubgraph(data, options({ focusEntityId: focus.entity_id }));

    expect(subgraph.data.edges.map((edge) => edge.relation_id).sort()).toEqual(["e1", "e2"]);
  });

  it("关系类型过滤：空集合不过滤，非空集合取交集", () => {
    const left = makeNode("c1", "甲");
    const right = makeNode("c2", "乙");
    const data = makeData(
      [left, right],
      [makeEdge("e1", left, right, "爱慕"), makeEdge("e2", left, right, "敌对")],
    );

    expect(buildGraphSubgraph(data, options()).data.edges).toHaveLength(2);
    const filtered = buildGraphSubgraph(data, options({ relationTypes: new Set(["敌对"]) }));
    expect(filtered.data.edges.map((edge) => edge.relation_id)).toEqual(["e2"]);
  });

  it("焦点不在筛选结果内时退回总览", () => {
    const hero = makeNode("c1", "顾霜");
    const city = makeNode("l1", "临安", "location");
    const data = makeData([hero, city], [makeEdge("e1", hero, city, "位于")]);

    const subgraph = buildGraphSubgraph(data, options({ focusEntityId: "l1" }));

    expect(subgraph.focusNode).toBeNull();
    expect(subgraph.data.nodes.map((node) => node.entity_id)).toEqual(["c1"]);
  });
});

describe("rankGraphNodes", () => {
  it("登场次数更高的节点排在前面", () => {
    const hero = makeNode("c1", "顾霜");
    const extra = makeNode("c2", "司夜");
    const data = makeData([hero, extra], [makeEdge("e1", hero, extra)]);

    const ranked = rankGraphNodes(data.nodes, data.edges, new Map([["顾霜", 9]]));

    expect(ranked[0].node.name).toBe("顾霜");
  });
});

describe("countEntitiesByType", () => {
  it("按类型统计并按数量降序", () => {
    const counts = countEntitiesByType([
      makeNode("c1", "甲"),
      makeNode("c2", "乙"),
      makeNode("l1", "临安", "location"),
    ]);

    expect(counts).toEqual([
      { type: "character", count: 2 },
      { type: "location", count: 1 },
    ]);
  });
});

describe("buildEntityRelationSummary", () => {
  it("按对端名与关系类型去重并累计支持次数", () => {
    const hero = makeNode("c1", "陈夏");
    const first = makeNode("c2", "许贞");
    const alias = makeNode("c3", "许贞");
    const rival = makeNode("c4", "黎月");
    const data = makeData(
      [hero, first, alias, rival],
      [
        makeEdge("e1", hero, first, "爱慕", 2),
        makeEdge("e2", hero, alias, "爱慕", 3),
        makeEdge("e3", hero, rival, "敌对", 1),
      ],
    );

    const summary = buildEntityRelationSummary(data, "c1");

    expect(summary.rawRelationCount).toBe(3);
    expect(summary.relationCount).toBe(2);
    expect(summary.entityCount).toBe(2);
    expect(summary.groups[0].relationType).toBe("爱慕");
    expect(summary.groups[0].items).toHaveLength(1);
    expect(summary.groups[0].items[0].supportCount).toBe(5);
    expect(summary.groups[1].relationType).toBe("敌对");
  });

  it("未选择实体时返回空汇总", () => {
    const summary = buildEntityRelationSummary(makeData([], []), null);
    expect(summary).toEqual({ groups: [], rawRelationCount: 0, relationCount: 0, entityCount: 0 });
  });
});
