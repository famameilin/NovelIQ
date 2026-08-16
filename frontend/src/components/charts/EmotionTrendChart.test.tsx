import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EmotionTrendChart } from "@/components/charts/EmotionTrendChart";
import { DEFAULT_SEED, useThemeStore } from "@/store/themeStore";
import type { EmotionTrendWindow } from "@/api/types";

let chartOnEvents: Record<string, (params: unknown) => void> = {};
let chartOption: {
  legend?: { data?: string[] };
  series?: Array<{ name?: string; type?: string; smooth?: boolean }>;
  yAxis?: { name?: string; min?: number; max?: number } | Array<unknown>;
} = {};

vi.mock("echarts-for-react", async () => {
  const React = await import("react");

  const MockChart = React.forwardRef(function MockChart(
    props: Record<string, unknown>,
    ref: React.ForwardedRef<unknown>,
  ) {
    void ref;
    chartOnEvents = (props.onEvents ?? {}) as Record<string, (params: unknown) => void>;
    chartOption = (props.option ?? {}) as typeof chartOption;
    return React.createElement("div", { "data-testid": "echarts-mock" });
  });

  return { default: MockChart };
});

vi.mock("@/lib/theme", () => ({
  getCSSColorVar: (name: string) => `hsl(${name})`,
  hslToHsla: (_color: string, alpha: number) => `hsla(0, 0%, 50%, ${alpha})`,
}));

function createWindow(overrides: Partial<EmotionTrendWindow> = {}): EmotionTrendWindow {
  return {
    window_index: 0,
    position: 0.025,
    start_position: 0,
    end_position: 0.05,
    paragraph_start: 0,
    paragraph_end: 14,
    chapter_start: 1,
    chapter_end: 1,
    pos_coverage: 0.4,
    neg_coverage: 0.2,
    pooled_pos_density: 0.01,
    pooled_neg_density: 0.005,
    pooled_net_density: 0.005,
    smoothed_pos_coverage: 0.4,
    smoothed_neg_coverage: 0.2,
    smoothed_pooled_pos_density: 0.01,
    smoothed_pooled_neg_density: 0.005,
    smoothed_pooled_net_density: 0.005,
    token_total: 500,
    hit_paragraphs: 8,
    paragraph_total: 15,
    ...overrides,
  };
}

describe("EmotionTrendChart", () => {
  beforeEach(() => {
    chartOnEvents = {};
    chartOption = {};
    useThemeStore.setState({
      seedColor: DEFAULT_SEED,
      isDark: false,
    });
  });

  it("窗口数据渲染不崩溃，池化密度空洞（null）保留", () => {
    render(
      <EmotionTrendChart
        data={[
          createWindow({ window_index: 0 }),
          createWindow({ window_index: 1, start_position: 0.05, end_position: 0.1, pooled_net_density: null }),
          createWindow({ window_index: 2, start_position: 0.1, end_position: 0.15 }),
        ]}
      />,
    );

    expect(screen.getByTestId("echarts-mock")).toBeInTheDocument();
  });

  it("只展示旧版四条情绪折线，不展示覆盖率辅助层", () => {
    render(<EmotionTrendChart data={[createWindow()]} />);

    expect(chartOption.legend?.data).toEqual([
      "正向强度",
      "负向强度",
      "原始趋势",
      "平滑趋势",
    ]);
    expect(chartOption.series).toHaveLength(4);
    expect(chartOption.series?.every((series) => series.type === "line")).toBe(true);
    expect(chartOption.series?.every((series) => series.smooth === true)).toBe(true);
    expect(chartOption.yAxis).toMatchObject({ name: "情绪密度" });
    expect(Array.isArray(chartOption.yAxis)).toBe(false);
  });

  it("点击窗口应触发 onPointClick 并回传当前窗口", () => {
    const onPointClick = vi.fn();
    const windows = [
      createWindow({ window_index: 0 }),
      createWindow({ window_index: 1, start_position: 0.05, end_position: 0.1 }),
    ];

    render(<EmotionTrendChart data={windows} onPointClick={onPointClick} />);

    act(() => {
      chartOnEvents.click?.({ dataIndex: 1 });
    });

    expect(onPointClick).toHaveBeenCalledTimes(1);
    expect(onPointClick).toHaveBeenCalledWith(windows[1]);
  });

  it("点击空白区域（无 dataIndex）不触发 onPointClick", () => {
    const onPointClick = vi.fn();

    render(<EmotionTrendChart data={[createWindow()]} onPointClick={onPointClick} />);

    act(() => {
      chartOnEvents.click?.({});
    });

    expect(onPointClick).not.toHaveBeenCalled();
  });
});
