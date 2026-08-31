import type { CSSProperties } from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { TopicShiftsPanel } from "@/components/topics/TopicShiftsPanel";

vi.mock("echarts-for-react", () => ({
  default: ({ style }: { style?: CSSProperties }) => <div data-testid="topic-shifts-chart" style={style} />,
}));

vi.mock("@/hooks/useChartThemeSignature", () => ({
  useChartThemeSignature: () => "test-theme",
}));

describe("TopicShiftsPanel", () => {
  it("使用统一表格外壳展示候选明细", () => {
    render(
      <TopicShiftsPanel
        candidates={[
          {
            position: 1200,
            paragraph_start: 10,
            paragraph_end: 15,
            score: 0.42,
            window_token_total: 1800,
          },
        ]}
        config={{
          window_size: 6,
          min_tokens_per_window: 800,
          score_threshold: 0.3,
          max_candidates: 20,
        }}
      />,
    );

    const table = screen.getByRole("table");
    expect(table.parentElement).toHaveClass("relative", "w-full", "overflow-auto");
    expect(screen.getByRole("columnheader", { name: "字符位置" })).toBeInTheDocument();
    expect(screen.getByText("0.4200")).toBeInTheDocument();
  });
});
