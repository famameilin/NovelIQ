/**
 * 事件森林「树内图外」布局纯函数单测
 *
 * 2026-08-19 P3：覆盖树分组、主链顺序、次因分支归组与跨树因果边识别。
 */
import { describe, expect, it } from "vitest";

import type { EventForestResponse } from "@/api/types";
import { createEventForest } from "@/mocks/data";

import { buildEventForestView } from "./eventForestLayout";

describe("buildEventForestView", () => {
  it("按 tree_id 组装树视图，主链保持原文顺序", () => {
    const view = buildEventForestView(createEventForest());

    expect(view.nodesById.size).toBe(5);
    expect(view.trees.map((tree) => tree.treeId)).toEqual(["tree-oath", "tree-ambush"]);

    const oath = view.trees[0];
    expect(oath.root.description).toBe("踏入山门");
    expect(oath.mainChain.map((node) => node.description)).toEqual([
      "踏入山门",
      "立下誓言",
      "兑现承诺",
    ]);
    expect(oath.secondaryGroups).toEqual([]);
    expect(oath.chapterRange).toBe("第 1–3 章");
  });

  it("把 secondary 节点按因果前驱 target 归组为次因分支", () => {
    const view = buildEventForestView(createEventForest());
    const ambush = view.trees[1];

    expect(ambush.root.description).toBe("路上遭遇劫匪");
    expect(ambush.mainChain.map((node) => node.description)).toEqual(["路上遭遇劫匪"]);
    expect(ambush.secondaryGroups).toHaveLength(1);
    expect(ambush.secondaryGroups[0].target.description).toBe("路上遭遇劫匪");
    expect(ambush.secondaryGroups[0].branch.map((node) => node.description)).toEqual([
      "劫匪提前得到消息",
    ]);
  });

  it("只把跨树因果边识别为 crossTreeEdges（树内边排除）", () => {
    const view = buildEventForestView(createEventForest());

    // edge-4（树间：tree-oath → tree-ambush）是跨树边；其余为树内边
    expect(view.crossTreeEdges.map((edge) => edge.edge_id)).toEqual(["edge-4"]);
  });

  it("忽略引用不存在节点的树，避免渲染悬空节点", () => {
    const data: EventForestResponse = {
      ...createEventForest(),
      event_trees: [
        {
          tree_id: "ghost",
          root_event_id: "missing-1",
          main_chain: ["missing-1", "missing-2"],
          secondary_groups: [],
          chapter_ids: [1],
          char_start: 0,
          char_end: 10,
        },
      ],
    };
    const view = buildEventForestView(data);

    expect(view.trees).not.toContainEqual(expect.objectContaining({ treeId: "ghost" }));
  });
});
