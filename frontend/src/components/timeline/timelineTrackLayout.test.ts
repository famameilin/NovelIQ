import { describe, expect, it } from "vitest";

import type { TimelineNode } from "@/api/types";

import {
  calculateCanvasMinWidth,
  createTimelineLayoutNodes,
  getClampedLabelLeftPx,
  getLabelTopPx,
  LABEL_HORIZONTAL_GAP_PX,
} from "./timelineTrackLayout";
import { buildTensionAreaPath, interpolateSeriesValueAtProgress, mapTensionValueToTrackY } from "./timelineTrackPaths";

/**
 * 2026-08-17，作用：构造用于时间轴布局测试的事件节点
 * 说明：保持节点字段完整，让布局测试只关注位置和车道
 */
function createNode(chapterId: number, progress: number, summary: string): TimelineNode {
  return {
    node_id: `plot:${chapterId}`,
    anchor_chapter_id: chapterId,
    progress,
    importance_score: 5,
    level: 1,
    summary,
    characters: [],
    phase_name: "发展期",
    node_type: "plot",
    node_subtype: "plot",
    score_breakdown: { tension: 1 },
    plot_flags: {
      is_pivot: false,
      is_cliffhanger: false,
      tension_percentile: 50,
    },
  };
}

describe("timelineTrackLayout", () => {
  it("会将密集事件分散到多个车道", () => {
    const nodes = [
      createNode(1, 0.2, "甲乙丙丁戊己庚辛"),
      createNode(2, 0.22, "甲乙丙丁戊己庚辛"),
      createNode(3, 0.24, "甲乙丙丁戊己庚辛"),
    ];

    const layoutNodes = createTimelineLayoutNodes(nodes, calculateCanvasMinWidth(nodes.length, 12));

    expect(new Set(layoutNodes.map((node) => node.lane)).size).toBeGreaterThan(1);
  });

  it("将卡片限制在画布横向边界内", () => {
    expect(getClampedLabelLeftPx(0, 180, 980)).toBeGreaterThanOrEqual(16);
    expect(getClampedLabelLeftPx(979, 180, 980)).toBeLessThanOrEqual(980 - 180 - 38);
  });

  it("同一进度事件保持全局顺序，并只让同一层卡片保留横向间距", () => {
    const nodes = Array.from({ length: 12 }, (_, index) =>
      createNode(index + 1, 0.5, `同点事件${index + 1}`),
    );
    const canvasWidth = calculateCanvasMinWidth(nodes.length, 120);
    const tensionCurve = [0, 1, ...Array.from({ length: 118 }, () => 0.5)];
    const layoutNodes = createTimelineLayoutNodes(nodes, canvasWidth, {
      tensionCurve,
      totalChapters: 120,
    });

    layoutNodes.forEach((layoutNode, index) => {
      expect(Math.abs(layoutNode.lane)).toBe(index % 2 === 0 ? 2 : 1);
      if (index > 0) {
        expect(layoutNode.anchorX).toBeGreaterThan(layoutNodes[index - 1]?.anchorX ?? 0);
      }
    });

    [-2, -1, 1, 2].forEach((lane) => {
      const intervals = layoutNodes
        .filter((layoutNode) => layoutNode.lane === lane)
        .map((layoutNode) => [
          layoutNode.anchorX - layoutNode.labelWidth / 2,
          layoutNode.anchorX + layoutNode.labelWidth / 2,
        ] as const)
        .sort((left, right) => left[0] - right[0]);

      intervals.slice(1).forEach((interval, index) => {
        expect(interval[0]).toBeGreaterThanOrEqual((intervals[index]?.[1] ?? 0) + LABEL_HORIZONTAL_GAP_PX);
      });
    });
  });

  it("中间线靠上时，下方先按第二层、第一层、第二层排布，并把下一张第一层放上方", () => {
    const nodes = Array.from({ length: 8 }, (_, index) =>
      createNode(index + 1, 0.8, `高线事件${index + 1}`),
    );
    const tensionCurve = [0, ...Array.from({ length: 19 }, () => 1)];
    const layoutNodes = createTimelineLayoutNodes(nodes, 980, {
      tensionCurve,
      totalChapters: 20,
    });

    expect(layoutNodes.map((layoutNode) => layoutNode.lane)).toEqual([2, 1, 2, -1, 2, 1, 2, -1]);
    expect(layoutNodes.map((layoutNode) => Math.abs(layoutNode.lane))).toEqual([2, 1, 2, 1, 2, 1, 2, 1]);
  });

  it("中间线靠下时，上方先按第二层、第一层、第二层排布，并把下一张第一层放下方", () => {
    const nodes = Array.from({ length: 8 }, (_, index) =>
      createNode(index + 1, 0.2, `低线事件${index + 1}`),
    );
    const tensionCurve = [1, ...Array.from({ length: 19 }, () => 0)];
    const layoutNodes = createTimelineLayoutNodes(nodes, 980, {
      tensionCurve,
      totalChapters: 20,
    });

    expect(layoutNodes.map((layoutNode) => layoutNode.lane)).toEqual([-2, -1, -2, 1, -2, -1, -2, 1]);
    expect(layoutNodes.map((layoutNode) => Math.abs(layoutNode.lane))).toEqual([2, 1, 2, 1, 2, 1, 2, 1]);
  });

  it("中间线居中时上下两侧都按成对车道交错", () => {
    const nodes = Array.from({ length: 4 }, (_, index) =>
      createNode(index + 1, 0.5, `居中事件${index + 1}`),
    );
    const tensionCurve = [0, 1, ...Array.from({ length: 18 }, () => 0.5)];
    const layoutNodes = createTimelineLayoutNodes(nodes, 980, {
      tensionCurve,
      totalChapters: 20,
    });

    expect(layoutNodes.map((layoutNode) => layoutNode.lane)).toEqual([-2, -1, 2, 1]);
    expect(layoutNodes.map((layoutNode) => Math.abs(layoutNode.lane))).toEqual([2, 1, 2, 1]);
  });

  it("卡片位置跟随中间线并保持上下间距", () => {
    expect(getLabelTopPx(233, -1)).toBe(153);
    expect(getLabelTopPx(233, -2)).toBe(73);
    expect(getLabelTopPx(233, 1)).toBe(277);
    expect(getLabelTopPx(233, 2)).toBe(352);
  });
});

describe("timelineTrackPaths", () => {
  it("构建张力底图 SVG 路径", () => {
    const result = buildTensionAreaPath([0.1, 0.5, 0.9], 3, 980);

    expect(result).not.toBeNull();
    expect(result?.linePath.startsWith("M ")).toBe(true);
    expect(result?.areaPath.endsWith(" Z")).toBe(true);
  });

  it("按进度插值张力序列", () => {
    const interpolated = interpolateSeriesValueAtProgress(0.25, [0, 1, 0], 3);

    expect(interpolated).toBeCloseTo(0.5, 5);
    expect(mapTensionValueToTrackY(1, [0, 1])).toBeLessThan(mapTensionValueToTrackY(0, [0, 1]));
  });
});
