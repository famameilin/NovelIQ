import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ProgressDetail } from "@/components/analysis/ProgressDetail";
import { useStreamStore } from "@/store/streamStore";

describe("ProgressDetail", () => {
  afterEach(() => {
    useStreamStore.getState().reset();
  });

  it("应按后端实际 sub_stage（chapter_agent/diagnosis）展示中文标签", () => {
    useStreamStore.getState().updateProgress({
      action: "start",
      stage: "annotate",
      sub_stage: "chapter_agent",
      chapter_id: 12,
      current: 12,
      total: 100,
      percent: 24,
      sub_percent: 0,
      content: "",
      message: "章节标注 Agent 开始",
    });

    const { rerender } = render(<ProgressDetail />);

    expect(screen.getByText("标注分析 - 标注 Agent")).toBeInTheDocument();
    expect(screen.getByText("标注 Agent")).toBeInTheDocument();

    useStreamStore.getState().updateProgress({
      action: "progress",
      stage: "diagnose",
      sub_stage: "diagnosis",
      chapter_id: 12,
      current: 12,
      total: 100,
      percent: 96,
      sub_percent: 25,
      content: "",
      message: "诊断进行中",
    });

    rerender(<ProgressDetail />);

    expect(screen.getByText("诊断报告 - 诊断")).toBeInTheDocument();
    expect(screen.getByText("诊断")).toBeInTheDocument();
  });

  it("应优先使用显式 stage，而不是仅凭 percent 推断当前阶段", () => {
    useStreamStore.getState().updateProgress({
      action: "progress",
      stage: "preprocess",
      sub_stage: "paragraph_embedding",
      chapter_id: 0,
      current: 658,
      total: 658,
      percent: 10,
      sub_percent: 100,
      content: "",
      message: "段落向量计算完成",
    });

    render(<ProgressDetail />);

    expect(screen.getByTestId("stage-item-preprocess")).toHaveAttribute("data-status", "current");
    expect(screen.getByTestId("stage-item-annotate")).toHaveAttribute("data-status", "pending");
    // 2026-08-13 P2：paragraph_embedding 子阶段应展示中文标签而非原始英文串
    expect(screen.getByText("段落向量")).toBeInTheDocument();
  });
});
