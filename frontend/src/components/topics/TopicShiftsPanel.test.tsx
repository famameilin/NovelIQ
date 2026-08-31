import type { CSSProperties } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

  it("默认展示差异最强的八项并允许展开完整明细", async () => {
    const user = userEvent.setup();
    const candidates = Array.from({ length: 10 }, (_, index) => ({
      position: (index + 1) * 100,
      paragraph_start: index * 2,
      paragraph_end: index * 2 + 1,
      score: (index + 1) / 100,
      window_token_total: 800 + index,
    }));

    render(<TopicShiftsPanel candidates={candidates} config={null} />);

    expect(screen.getAllByRole("row")).toHaveLength(9);
    expect(screen.queryByText("0.0100")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "查看全部 10 个变化位置" }));
    expect(screen.getAllByRole("row")).toHaveLength(11);
    expect(screen.getByText("0.0100")).toBeInTheDocument();
  });
});
