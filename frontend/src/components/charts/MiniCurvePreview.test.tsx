import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MiniCurvePreview } from "@/components/charts/MiniCurvePreview";
import { DEFAULT_SEED, useThemeStore } from "@/store/themeStore";

const navigateMock = vi.fn();
let chartMountCount = 0;
let chartUnmountCount = 0;

vi.mock("react-router-dom", () => ({
  useNavigate: () => navigateMock,
}));

vi.mock("echarts-for-react", async () => {
  const React = await import("react");

  const MockChart = React.forwardRef(function MockChart(
    _props: Record<string, unknown>,
    _ref: React.ForwardedRef<unknown>,
  ) {
    void _props;
    void _ref;
    React.useEffect(() => {
      chartMountCount += 1;
      return () => {
        chartUnmountCount += 1;
      };
    }, []);

    return React.createElement("div", { "data-testid": "echarts-mock" });
  });

  return { default: MockChart };
});

describe("MiniCurvePreview", () => {
  beforeEach(() => {
    navigateMock.mockReset();
    chartMountCount = 0;
    chartUnmountCount = 0;
    useThemeStore.setState({
      seedColor: DEFAULT_SEED,
      isDark: false,
    });
  });

  it("主题签名变化时应重建图表实例，避免旧新 option 差量动画崩溃", async () => {
    render(
      <MiniCurvePreview
        novelId="novel-1"
        data={[
          {
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
            pooled_pos_density: 0.1,
            pooled_neg_density: 0.2,
            pooled_net_density: -0.1,
            smoothed_pos_coverage: 0.4,
            smoothed_neg_coverage: 0.2,
            smoothed_pooled_pos_density: 0.1,
            smoothed_pooled_neg_density: 0.2,
            smoothed_pooled_net_density: -0.1,
            token_total: 500,
            hit_paragraphs: 8,
            paragraph_total: 15,
          },
        ]}
      />,
    );

    expect(screen.getByTestId("echarts-mock")).toBeInTheDocument();
    expect(chartMountCount).toBe(1);
    expect(chartUnmountCount).toBe(0);

    act(() => {
      useThemeStore.getState().setSeedColor("#123456");
    });

    await waitFor(() => {
      expect(chartMountCount).toBe(2);
      expect(chartUnmountCount).toBe(1);
    });
  });
});
