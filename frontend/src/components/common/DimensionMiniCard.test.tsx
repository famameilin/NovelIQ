import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DimensionMiniCard } from "@/components/common/DimensionMiniCard";

describe("DimensionMiniCard", () => {
  it("所有指标缺失时显示样本不足而不是零值", () => {
    render(<DimensionMiniCard dimension="emotion" data={{}} novelId="novel-1" />);

    expect(screen.getAllByText("样本不足").length).toBeGreaterThan(0);
    expect(screen.queryByText("0.00")).not.toBeInTheDocument();
  });

  it("情绪卡只展示正向密度和负向密度", () => {
    render(
      <DimensionMiniCard
        dimension="emotion"
        data={{
          lexical_positive_density: 0.006,
          lexical_negative_density: 0.004,
        }}
        novelId="novel-1"
      />,
    );

    expect(screen.getByText("正向密度")).toBeInTheDocument();
    expect(screen.getByText("负向密度")).toBeInTheDocument();
    expect(screen.queryByText(/语义极性/)).not.toBeInTheDocument();
    expect(screen.queryByText(/角色情感波动/)).not.toBeInTheDocument();
    expect(screen.queryByText("标注派生")).not.toBeInTheDocument();
  });
});
