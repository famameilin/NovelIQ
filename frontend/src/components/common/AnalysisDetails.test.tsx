import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AnalysisDetails } from "@/components/common/AnalysisDetails";

describe("AnalysisDetails", () => {
  it("首次展开后才挂载延迟内容", async () => {
    render(
      <AnalysisDetails lazy title="完整分析">
        <div>延迟图表</div>
      </AnalysisDetails>,
    );

    expect(screen.queryByText("延迟图表")).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("完整分析"));
    await waitFor(() => expect(screen.getByText("延迟图表")).toBeInTheDocument());
  });

  it("默认展开时立即挂载延迟内容", () => {
    render(
      <AnalysisDetails lazy defaultOpen title="模型详情">
        <div>模型参数</div>
      </AnalysisDetails>,
    );

    expect(screen.getByText("模型参数")).toBeInTheDocument();
  });
});
