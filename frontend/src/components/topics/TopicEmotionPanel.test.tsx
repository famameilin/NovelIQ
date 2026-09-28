import type { CSSProperties } from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { TopicEmotionPanel } from "@/components/topics/TopicEmotionPanel";

vi.mock("echarts-for-react", () => ({
  default: ({ style, option }: {
    style?: CSSProperties;
    option: {
      xAxis: { data: string[] };
      tooltip: { formatter: (params: Array<{ dataIndex: number }>) => string };
    };
  }) => (
    <div
      data-testid="topic-emotion-chart"
      data-labels={option.xAxis.data.join("|")}
      data-tooltip={option.tooltip.formatter([{ dataIndex: 0 }])}
      style={style}
    />
  ),
}));

vi.mock("@/hooks/useChartThemeSignature", () => ({
  useChartThemeSignature: () => "test-theme",
}));

vi.mock("@/hooks/useInView", () => ({
  useInView: () => ({ ref: { current: null }, isVisible: true }),
}));

describe("TopicEmotionPanel", () => {
  it("为图表建立可填满工作区的确定高度链", () => {
    render(
      <TopicEmotionPanel
        emotion={[{ topic_id: 0, emotion: 0.25, weighted_token_total: 1200 }]}
      />,
    );

    const chart = screen.getByTestId("topic-emotion-chart");
    expect(chart).toHaveStyle({ height: "100%", width: "100%" });
    expect(chart.parentElement).toHaveClass("h-full", "min-h-[320px]", "w-full");
    expect(chart.parentElement?.parentElement).toHaveClass("min-h-0", "flex-1");
  });

  it("按主题 ID 展示名称，未命名主题才使用编号", () => {
    render(
      <TopicEmotionPanel
        emotion={[
          { topic_id: 3, emotion: 0.25, weighted_token_total: 1200 },
          { topic_id: 8, emotion: -0.1, weighted_token_total: 500 },
        ]}
        topicLabels={{ 3: "太学课业" }}
      />,
    );

    const chart = screen.getByTestId("topic-emotion-chart");
    expect(chart).toHaveAttribute("data-labels", "太学课业|主题 9");
    expect(chart.getAttribute("data-tooltip")).toContain("太学课业");
  });
});
