import { describe, expect, it, vi } from "vitest";

import { createForceGraphPalette } from "@/components/charts/forceGraph/forceGraphPalette";

/**
 * 2026-08-12 用于锁住关系类型配色表与后端 RELATION_DEFINITIONS 12 词全表对齐：
 * 展示层必须包含「领导」，否则图例/主图对该关系回退到默认配色
 */
vi.mock("@/lib/theme", () => ({
  getCSSColorVar: (name: string) => `var(${name})`,
}));

describe("forceGraphPalette 关系类型配色", () => {
  it("关系类型表包含与后端 RELATION_DEFINITIONS 一致的 12 词全表", () => {
    const { relationColors } = createForceGraphPalette();

    expect(Object.keys(relationColors)).toEqual([
      "家族",
      "师徒",
      "主从",
      "敌对",
      "盟友",
      "友情",
      "爱慕",
      "利益",
      "领导",
      "同一人物",
      "隶属",
      "位于",
    ]);
  });

  it("「领导」与其他层级型关系一样使用中性色", () => {
    const { relationColors } = createForceGraphPalette();
    expect(relationColors["领导"]).toBe("var(--chart-neutral)");
  });
});
