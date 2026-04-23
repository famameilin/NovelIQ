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
            chunk_id: 0,
            pos_density: 0.1,
            neg_density: 0.2,
            net_density: 0.0,
            smoothed_density: 0.05,
            tension_proxy: null,
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
