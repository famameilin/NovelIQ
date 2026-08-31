import type { CSSProperties } from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { TopicEmotionPanel } from "@/components/topics/TopicEmotionPanel";

vi.mock("echarts-for-react", () => ({
  default: ({ style }: { style?: CSSProperties }) => (
    <div data-testid="topic-emotion-chart" style={style} />
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
    expect(chart.parentElement).toHaveClass("h-[320px]", "w-full");
    expect(chart.parentElement?.parentElement).toHaveClass("min-h-0", "flex-1");
  });
});
