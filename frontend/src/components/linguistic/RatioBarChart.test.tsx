import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { RatioBarChart } from "@/components/linguistic/RatioBarChart";

describe("RatioBarChart", () => {
  it("格式化标签时仍通过 title 保留原始枚举键", () => {
    render(
      <RatioBarChart
        title="词性比例"
        ratios={{ noun: 0.6 }}
        formatLabel={() => "名词"}
      />,
    );

    expect(screen.getByText("名词")).toHaveAttribute("title", "noun");
  });

  it("分页后仍可查看末尾比例项", async () => {
    const user = userEvent.setup();
    render(<RatioBarChart title="词性比例" ratios={{ a: 5, b: 4, c: 3, d: 2, e: 1 }} pageSize={2} />);

    expect(screen.getByText("a")).toBeInTheDocument();
    expect(screen.queryByText("e")).not.toBeInTheDocument();
    const controls = screen.getByRole("navigation", { name: "词性比例分页" });
    await user.click(within(controls).getByRole("button", { name: "下一页" }));
    await user.click(within(controls).getByRole("button", { name: "下一页" }));
    expect(screen.getByText("e")).toBeInTheDocument();
    expect(screen.queryByText("a")).not.toBeInTheDocument();
  });

  it("两类计数以构成图和原始计数展示，不拉伸成空白卡片", () => {
    render(
      <RatioBarChart
        title="实体类型计数"
        ratios={{ person: 1478, location: 354 }}
        columns={2}
        presentation="composition"
        formatLabel={(key) => key === "person" ? "人物" : "地点"}
        formatValue={String}
      />,
    );

    expect(screen.getByRole("img", { name: "实体类型计数构成图" }).style.background).toContain("conic-gradient");
    expect(screen.getByText("80.7%")).toBeInTheDocument();
    expect(screen.getByText("1478")).toBeInTheDocument();
    expect(screen.getByText("354")).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "实体类型计数分页" })).not.toBeInTheDocument();
  });

  it("可能重叠的句式指标保留原始比例，使用单列排行", () => {
    render(<RatioBarChart title="句式比例" ratios={{ medium: 0.415, short: 0.296, long: 0.289, compound: 0.016, parallel: 0.005 }} columns={2} />);

    expect(screen.queryByRole("img", { name: "句式比例构成图" })).not.toBeInTheDocument();
    expect(within(screen.getByTestId("distribution-ranking")).getAllByRole("listitem")).toHaveLength(5);
    expect(screen.getByText("41.5%")).toBeInTheDocument();
  });

  it("十四类在双列单页呈现，超出容量时均衡分页", async () => {
    const ratios = Object.fromEntries(Array.from({ length: 14 }, (_, index) => [`type-${index + 1}`, 14 - index]));
    const { rerender } = render(<RatioBarChart title="依存关系" ratios={ratios} columns={2} pageSize={14} />);

    expect(within(screen.getByTestId("distribution-ranking")).getAllByRole("listitem")).toHaveLength(14);
    expect(screen.queryByRole("navigation", { name: "依存关系分页" })).not.toBeInTheDocument();

    rerender(<RatioBarChart title="依存关系" ratios={ratios} columns={2} pageSize={10} />);
    expect(within(screen.getByTestId("distribution-ranking")).getAllByRole("listitem")).toHaveLength(7);
    await userEvent.setup().click(screen.getByRole("button", { name: "下一页" }));
    expect(within(screen.getByTestId("distribution-ranking")).getAllByRole("listitem")).toHaveLength(7);
    expect(screen.getByText("type-14")).toBeInTheDocument();
  });
});
