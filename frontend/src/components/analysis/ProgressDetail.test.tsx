import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ProgressDetail } from "@/components/analysis/ProgressDetail";
import { useStreamStore } from "@/store/streamStore";

describe("ProgressDetail", () => {
  afterEach(() => {
    useStreamStore.getState().reset();
  });

  it("应按后端真实语义展示 phase1 和 phase2 的中文标签", () => {
    useStreamStore.getState().updateProgress({
      action: "start",
      stage: "annotate",
      sub_stage: "phase1",
      chunk_id: 12,
      current: 12,
      total: 100,
      percent: 24,
      sub_percent: 0,
      content: "",
      message: "开始 phase1",
    });

    const { rerender } = render(<ProgressDetail />);

    expect(screen.getByText("标注分析 - 人物识别")).toBeInTheDocument();
    expect(screen.getByText("人物识别")).toBeInTheDocument();

    useStreamStore.getState().updateProgress({
      action: "start",
      stage: "annotate",
      sub_stage: "phase2",
      chunk_id: 12,
      current: 12,
      total: 100,
      percent: 36,
      sub_percent: 25,
      content: "",
      message: "开始 phase2",
    });

    rerender(<ProgressDetail />);

    expect(screen.getByText("标注分析 - 伏笔分析")).toBeInTheDocument();
    expect(screen.getByText("伏笔分析")).toBeInTheDocument();
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
