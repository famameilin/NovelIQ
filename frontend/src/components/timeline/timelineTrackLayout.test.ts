import { describe, expect, it } from "vitest";

import type { TimelineNode } from "@/api/types";

import {
  calculateCanvasMinWidth,
  createTimelineLayoutNodes,
  getClampedLabelLeftPx,
} from "./timelineTrackLayout";
import { buildTensionAreaPath, interpolateSeriesValueAtProgress, mapTensionValueToTrackY } from "./timelineTrackPaths";

function createNode(chunkId: number, progress: number, summary: string): TimelineNode {
  return {
    node_id: `plot:${chunkId}`,
    anchor_chunk_id: chunkId,
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
  it("spreads dense labels across multiple lanes", () => {
    const nodes = [
      createNode(1, 0.2, "甲乙丙丁戊己庚辛"),
      createNode(2, 0.22, "甲乙丙丁戊己庚辛"),
      createNode(3, 0.24, "甲乙丙丁戊己庚辛"),
    ];

    const layoutNodes = createTimelineLayoutNodes(nodes, calculateCanvasMinWidth(nodes.length, 12));

    expect(new Set(layoutNodes.map((node) => node.lane)).size).toBeGreaterThan(1);
  });

  it("clamps labels inside the canvas bounds", () => {
    expect(getClampedLabelLeftPx(0, 180, 980)).toBeGreaterThanOrEqual(16);
    expect(getClampedLabelLeftPx(979, 180, 980)).toBeLessThanOrEqual(980 - 180 - 38);
  });
});

describe("timelineTrackPaths", () => {
  it("builds SVG paths for the tension area", () => {
    const result = buildTensionAreaPath([0.1, 0.5, 0.9], 3, 980);

    expect(result).not.toBeNull();
    expect(result?.linePath.startsWith("M ")).toBe(true);
    expect(result?.areaPath.endsWith(" Z")).toBe(true);
  });

  it("interpolates tension values along progress", () => {
    const interpolated = interpolateSeriesValueAtProgress(0.25, [0, 1, 0], 3);

    expect(interpolated).toBeCloseTo(0.5, 5);
    expect(mapTensionValueToTrackY(1, [0, 1])).toBeLessThan(mapTensionValueToTrackY(0, [0, 1]));
  });
});
