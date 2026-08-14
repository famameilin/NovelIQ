import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EmotionCurveChart } from "@/components/charts/EmotionCurveChart";
import { DEFAULT_SEED, useThemeStore } from "@/store/themeStore";
import type { ParagraphCurvePoint } from "@/api/types";

let chartOnEvents: Record<string, (params: unknown) => void> = {};

vi.mock("echarts-for-react", async () => {
  const React = await import("react");

  const MockChart = React.forwardRef(function MockChart(
    props: Record<string, unknown>,
    ref: React.ForwardedRef<unknown>,
  ) {
    void ref;
    chartOnEvents = (props.onEvents ?? {}) as Record<string, (params: unknown) => void>;
    return React.createElement("div", { "data-testid": "echarts-mock" });
  });

  return { default: MockChart };
});

function createPoint(overrides: Partial<ParagraphCurvePoint> = {}): ParagraphCurvePoint {
  return {
    paragraph_id: 1,
    chapter_id: 1,
    paragraph_index: 0,
    global_start_char: 0,
    global_end_char: 60,
    position: 0,
    char_count: 60,
    token_count: 38,
    pos_density: 0.1,
    neg_density: 0.2,
    net_density: 0.0,
    smoothed_net_density: 0.05,
    surface_tension: 0.4,
    smoothed_surface_tension: 0.35,
    ...overrides,
  };
}

describe("EmotionCurveChart", () => {
  beforeEach(() => {
    chartOnEvents = {};
    useThemeStore.setState({
      seedColor: DEFAULT_SEED,
      isDark: false,
    });
  });

  it("段落粒度数据渲染不崩溃，且 position 空洞（null 值）保留为 null", () => {
    render(
      <EmotionCurveChart
        data={[
          createPoint({ position: 0 }),
          createPoint({ position: 0.5, net_density: null, paragraph_id: 2 }),
          createPoint({ position: 1, paragraph_id: 3 }),
        ]}
      />,
    );

    expect(screen.getByTestId("echarts-mock")).toBeInTheDocument();
  });

  it("点击曲线点应触发 onPointClick 并回传当前数据点", () => {
    const onPointClick = vi.fn();
    const points = [
      createPoint({ paragraph_id: 1, position: 0.2 }),
      createPoint({ paragraph_id: 2, position: 0.8 }),
    ];

    render(<EmotionCurveChart data={points} onPointClick={onPointClick} />);

    act(() => {
      chartOnEvents.click?.({ dataIndex: 1 });
    });

    expect(onPointClick).toHaveBeenCalledTimes(1);
    expect(onPointClick).toHaveBeenCalledWith(points[1]);
  });

  it("点击空白区域（无 dataIndex）不触发 onPointClick", () => {
    const onPointClick = vi.fn();

    render(<EmotionCurveChart data={[createPoint()]} onPointClick={onPointClick} />);

    act(() => {
      chartOnEvents.click?.({});
    });

    expect(onPointClick).not.toHaveBeenCalled();
  });
});
