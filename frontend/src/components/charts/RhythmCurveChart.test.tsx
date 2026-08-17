import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RhythmCurveChart } from "@/components/charts/RhythmCurveChart";
import { DEFAULT_SEED, useThemeStore } from "@/store/themeStore";
import type { ParagraphCurvePoint } from "@/api/types";

let chartOption: {
  tooltip?: {
    formatter?: (params: Array<{
      seriesName: string;
      value: number | [number, number | null] | null;
      marker: string;
      dataIndex?: number;
    }>) => string;
  };
  series?: Array<{ emphasis?: { disabled?: boolean }; markLine?: unknown }>;
} = {};

vi.mock("echarts-for-react", async () => {
  const React = await import("react");

  const MockChart = React.forwardRef(function MockChart(
    props: Record<string, unknown>,
    ref: React.ForwardedRef<unknown>,
  ) {
    void ref;
    chartOption = (props.option ?? {}) as typeof chartOption;
    return React.createElement("div", { "data-testid": "echarts-mock" });
  });

  return { default: MockChart };
});

vi.mock("@/lib/theme", () => ({
  getCSSColorVar: (name: string) => `hsl(${name})`,
}));

/**
 * 2026-08-16 创建节奏曲线测试数据
 * 用于验证 value 轴下 tooltip 对 [x, y] 点位的展示
 */
function createPoint(overrides: Partial<ParagraphCurvePoint> = {}): ParagraphCurvePoint {
  return {
    paragraph_id: 1,
    chapter_id: 3,
    paragraph_index: 4,
    global_start_char: 0,
    global_end_char: 80,
    position: 0.25,
    char_count: 80,
    token_count: 50,
    pos_density: 0.2,
    neg_density: 0.1,
    net_density: 0.1,
    smoothed_net_density: 0.1,
    surface_tension: 0.72,
    smoothed_surface_tension: 0.68,
    ...overrides,
  };
}

describe("RhythmCurveChart", () => {
  beforeEach(() => {
    chartOption = {};
    useThemeStore.setState({
      seedColor: DEFAULT_SEED,
      isDark: false,
    });
  });

  it("数值轴悬浮时应展示 [x, y] 数据点的 y 值", () => {
    render(<RhythmCurveChart data={[createPoint()]} />);

    expect(screen.getByTestId("echarts-mock")).toBeInTheDocument();
    const tooltip = chartOption.tooltip?.formatter?.([
      {
        seriesName: "表层张力",
        value: [0.25, 0.72],
        marker: "",
        dataIndex: 0,
      },
      {
        seriesName: "平滑张力",
        value: [0.25, 0.68],
        marker: "",
        dataIndex: 0,
      },
    ]);

    expect(tooltip).toContain("第 3 章 第 5 段");
    expect(tooltip).toContain("0.7200");
    expect(tooltip).toContain("0.6800");
    expect(chartOption.series?.every((series) => series.emphasis?.disabled === true)).toBe(true);
  });

  it("三幕比例全为空时不绘制分界线和高潮标记", () => {
    render(
      <RhythmCurveChart
        data={[createPoint()]}
        narrativeStructure={{ act1_ratio: null, act2_ratio: null, act3_ratio: null, climax_positions: null }}
      />,
    );

    expect(chartOption.series?.every((series) => series.markLine == null)).toBe(true);
  });
});
