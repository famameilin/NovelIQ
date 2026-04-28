import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ProgressDetail } from "@/components/analysis/ProgressDetail";
import { useStreamStore } from "@/store/streamStore";

describe("ProgressDetail", () => {
  afterEach(() => {
    useStreamStore.getState().reset();
  });

  it("应优先使用显式 stage，而不是仅凭 percent 推断当前阶段", () => {
    useStreamStore.getState().updateProgress({
      action: "progress",
      stage: "preprocess",
      sub_stage: "semantic_chunking_embedding",
      chunk_id: 0,
      current: 658,
      total: 658,
      percent: 10,
      sub_percent: 100,
      content: "",
      message: "语义分块段落向量计算完成",
    });

    render(<ProgressDetail />);

    expect(screen.getByTestId("stage-item-preprocess")).toHaveAttribute("data-status", "current");
    expect(screen.getByTestId("stage-item-annotate")).toHaveAttribute("data-status", "pending");
  });
});
