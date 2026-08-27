import { describe, expect, it } from "vitest";

import type { TimelineEventNode } from "@/api/types";

import {
  calculateCanvasMinWidth,
  createTimelineLayoutNodes,
  getClampedLabelLeftPx,
  getEventSpanWidth,
  getLabelTopPx,
  LABEL_HORIZONTAL_GAP_PX,
  TRACK_NODE_END_PADDING_PX,
  TRACK_NODE_START_PADDING_PX,
} from "./timelineTrackLayout";
import { buildTensionAreaPath, interpolateSeriesValueAtProgress, mapTensionValueToTrackY } from "./timelineTrackPaths";

/**
 * 2026-08-17，作用：构造用于时间轴布局测试的事件节点（兼容新一树一节点合同）
 */
function createEventNode(
  treeId: string,
  chapterId: number,
  progress: number,
  summary: string,
  overrides?: Partial<TimelineEventNode>,
): TimelineEventNode {
  return {
    tree_id: treeId,
    root_event_id: `evt-${treeId}`,
    title: summary,
    summary,
    anchor_chapter_id: chapterId,
    anchor_chapter_order: chapterId,
    start_chapter_id: chapterId,
    end_chapter_id: chapterId,
    start_progress: progress,
    end_progress: progress,
    progress,
    chapter_ids: [chapterId],
    char_start: 0,
    char_end: 100,
    participants: [],
    character_names: [],
    importance_score: 5,
    level: 1,
    phase_name: "发展期",
    main_chain: [],
    secondary_groups: [],
    causal_in: 0,
    causal_out: 0,
    node_type: "event",
    ...overrides,
  };
}

// 兼容旧 helper 保留
function createNode(chapterId: number, progress: number, summary: string): TimelineEventNode {
  return createEventNode(`plot:${chapterId}`, chapterId, progress, summary);
}

describe("timelineTrackLayout", () => {
  it("会将密集事件分散到多个车道", () => {
    const nodes = [
      createNode(1, 0.2, "甲乙丙丁戊己庚辛"),
      createNode(2, 0.22, "甲乙丙丁戊己庚辛"),
      createNode(3, 0.24, "甲乙丙丁戊己庚辛"),
    ];
    const derivedOrder = nodes.map((n) => n.tree_id);
    const layoutNodes = createTimelineLayoutNodes(nodes, derivedOrder, calculateCanvasMinWidth(nodes.length, 12));

    expect(new Set(layoutNodes.map((node) => node.lane)).size).toBeGreaterThan(1);
  });

  it("将卡片限制在画布横向边界内", () => {
    expect(getClampedLabelLeftPx(0, 180, 980)).toBeGreaterThanOrEqual(16);
    expect(getClampedLabelLeftPx(979, 180, 980)).toBeLessThanOrEqual(980 - 180 - 38);
  });

  it("同一进度事件保持全局顺序，并只让同一层卡片保留横向间距", () => {
    const nodes = Array.from({ length: 12 }, (_, index) =>
      createEventNode(`t${index + 1}`, index + 1, 0.5, `同点事件${index + 1}`),
    );
    const derivedOrder = nodes.map((n) => n.tree_id);
    const canvasWidth = calculateCanvasMinWidth(nodes.length, 120);
    const tensionCurve = [0, 1, ...Array.from({ length: 118 }, () => 0.5)];
    const layoutNodes = createTimelineLayoutNodes(nodes, derivedOrder, canvasWidth, {
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
      createEventNode(`h${index + 1}`, index + 1, 0.8, `高线事件${index + 1}`),
    );
    const derivedOrder = nodes.map((n) => n.tree_id);
    const tensionCurve = [0, ...Array.from({ length: 19 }, () => 1)];
    const layoutNodes = createTimelineLayoutNodes(nodes, derivedOrder, 980, {
      tensionCurve,
      totalChapters: 20,
    });

    expect(layoutNodes.map((layoutNode) => layoutNode.lane)).toEqual([2, 1, 2, -1, 2, 1, 2, -1]);
    expect(layoutNodes.map((layoutNode) => Math.abs(layoutNode.lane))).toEqual([2, 1, 2, 1, 2, 1, 2, 1]);
  });

  it("中间线靠下时，上方先按第二层、第一层、第二层排布，并把下一张第一层放下方", () => {
    const nodes = Array.from({ length: 8 }, (_, index) =>
      createEventNode(`l${index + 1}`, index + 1, 0.2, `低线事件${index + 1}`),
    );
    const derivedOrder = nodes.map((n) => n.tree_id);
    const tensionCurve = [1, ...Array.from({ length: 19 }, () => 0)];
    const layoutNodes = createTimelineLayoutNodes(nodes, derivedOrder, 980, {
      tensionCurve,
      totalChapters: 20,
    });

    expect(layoutNodes.map((layoutNode) => layoutNode.lane)).toEqual([-2, -1, -2, 1, -2, -1, -2, 1]);
    expect(layoutNodes.map((layoutNode) => Math.abs(layoutNode.lane))).toEqual([2, 1, 2, 1, 2, 1, 2, 1]);
  });

  it("中间线居中时上下两侧都按成对车道交错", () => {
    const nodes = Array.from({ length: 4 }, (_, index) =>
      createEventNode(`m${index + 1}`, index + 1, 0.5, `居中事件${index + 1}`),
    );
    const derivedOrder = nodes.map((n) => n.tree_id);
    const tensionCurve = [0, 1, ...Array.from({ length: 18 }, () => 0.5)];
    const layoutNodes = createTimelineLayoutNodes(nodes, derivedOrder, 980, {
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

  it("按 derivedOrder 均匀分布 anchorX，而非按 progress 聚簇", () => {
    // progress 故意打乱，但 derivedOrder 要求均匀
    const nodes = [
      createEventNode("tA", 10, 0.9, "事件A"),
      createEventNode("tB", 2, 0.1, "事件B"),
      createEventNode("tC", 5, 0.5, "事件C"),
      createEventNode("tD", 8, 0.8, "事件D"),
      createEventNode("tE", 1, 0.05, "事件E"),
    ];
    const derivedOrder = ["tE", "tB", "tC", "tD", "tA"];
    const canvasWidth = 1200;
    const usableWidth = canvasWidth - TRACK_NODE_START_PADDING_PX - TRACK_NODE_END_PADDING_PX;
    const layoutNodes = createTimelineLayoutNodes(nodes, derivedOrder, canvasWidth, {
      totalChapters: 20,
    });

    // 验证顺序严格跟随 derivedOrder
    expect(layoutNodes.map((n) => n.node.tree_id)).toEqual(derivedOrder);
    // 验证均匀分布：间距近似相等，容差考虑 pack 最小间距微调及首尾 label 边界约束（START 28 vs 16+半宽）
    for (let i = 1; i < layoutNodes.length; i++) {
      const gap = (layoutNodes[i]?.anchorX ?? 0) - (layoutNodes[i - 1]?.anchorX ?? 0);
      const expectedGap = usableWidth / (nodes.length - 1);
      // 均匀分布后 pack 仅做最小间距和边界钳制，首尾因 LABEL_START_GAP 会偏移，中间间距仍应接近均匀
      expect(Math.abs(gap - expectedGap)).toBeLessThan(80);
    }
    // progress 乱序不应影响 anchorX 单调性
    for (let i = 1; i < layoutNodes.length; i++) {
      expect(layoutNodes[i]?.anchorX).toBeGreaterThan(layoutNodes[i - 1]?.anchorX ?? 0);
    }
  });

  it("跨章区间返回带宽而单章返回标签宽度", () => {
    const canvasWidth = 1000;
    const crossNode = createEventNode("cross", 2, 0.3, "跨章事件", {
      start_chapter_id: 2,
      end_chapter_id: 5,
      start_progress: 0.2,
      end_progress: 0.5,
      chapter_ids: [2, 3, 4, 5],
    });
    const singleNode = createEventNode("single", 3, 0.4, "单章事件");
    const usableWidth = canvasWidth - TRACK_NODE_START_PADDING_PX - TRACK_NODE_END_PADDING_PX;
    const spanWidth = getEventSpanWidth(crossNode, canvasWidth, 20);
    expect(spanWidth).toBeCloseTo(0.3 * usableWidth, 5);
    const singleWidth = getEventSpanWidth(singleNode, canvasWidth, 20);
    expect(singleWidth).toBeGreaterThanOrEqual(164);
    expect(singleWidth).toBeLessThanOrEqual(196);
  });

  it.skip("旧 progress 排序已废弃，仅保留均匀分布", () => {
    // 旧接口按 progress 排序现已被 derivedOrder 取代，此用例标记跳过以记录迁移
    const nodes = [createNode(2, 0.8, "旧排序2"), createNode(1, 0.1, "旧排序1")];
    const derivedOrder: string[] = [];
    const layout = createTimelineLayoutNodes(nodes, derivedOrder, 980);
    expect(layout[0]?.node.progress).toBeLessThan(layout[1]?.node.progress ?? 1);
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
