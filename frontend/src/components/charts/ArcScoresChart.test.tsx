import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ArcScoresChart } from "@/components/charts/ArcScoresChart";

vi.mock("echarts-for-react", () => ({
  default: ({ option }: { option: { yAxis: { data: string[] }; series: { data: number[] }[] } }) => (
    <div aria-label="图表数据">
      {option.yAxis.data.map((name, index) => <p key={name}>{name}：{option.series[0].data[index]}</p>)}
    </div>
  ),
}));

describe("ArcScoresChart", () => {
  it("按全集评分排序后分页，十二名之后的记录仍然可达", async () => {
    const user = userEvent.setup();
    render(<ArcScoresChart arcScores={Object.fromEntries(
      Array.from({ length: 25 }, (_, index) => [`人物${index + 1}`, index / 3]),
    )} />);
    const chart = screen.getByLabelText("图表数据");
    expect(within(chart).getAllByText(/人物/)).toHaveLength(12);
    expect(within(chart).getAllByText(/人物/)[0]).toHaveTextContent("人物25：8");
    expect(within(chart).queryByText("人物1：0")).not.toBeInTheDocument();
    const pagination = screen.getByRole("navigation", { name: "角色弧线分页" });
    await user.click(within(pagination).getByRole("button", { name: "下一页" }));
    await user.click(within(pagination).getByRole("button", { name: "下一页" }));
    expect(within(chart).getByText("人物1：0")).toBeInTheDocument();
    expect(within(chart).getAllByText(/人物/)).toHaveLength(1);
  });
});
