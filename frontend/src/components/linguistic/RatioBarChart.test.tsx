import { render, screen } from "@testing-library/react";
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
});
