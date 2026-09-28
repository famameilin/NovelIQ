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

  it("按强度分页展示全部明细且不出现内部纵向滚动", async () => {
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
    expect(screen.getByRole("navigation", { name: "变化明细 · 共 10 个分页" })).toBeInTheDocument();
    expect(screen.getByRole("table").parentElement?.parentElement).not.toHaveClass("overflow-y-auto");
    await user.click(screen.getByRole("button", { name: "下一页" }));
    expect(screen.getAllByRole("row")).toHaveLength(3);
    expect(screen.getByText("0.0100")).toBeInTheDocument();
  });
});
