import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import type { TimelineNode, TimelinePhase } from "@/api/types";
import { TimelineTrack } from "./TimelineTrack";

vi.mock("framer-motion", () => ({
  motion: {
    div: (props: Record<string, unknown>) => {
      const sanitizedProps = { ...props };
      delete sanitizedProps.initial;
      delete sanitizedProps.animate;
      delete sanitizedProps.transition;
      return <div {...sanitizedProps}>{props.children as ReactNode}</div>;
    },
    button: (props: Record<string, unknown>) => {
      const sanitizedProps = { ...props };
      delete sanitizedProps.initial;
      delete sanitizedProps.animate;
      delete sanitizedProps.transition;
      delete sanitizedProps.whileHover;
      return <button {...sanitizedProps}>{props.children as ReactNode}</button>;
    },
  },
}));

function createNode(overrides: Partial<TimelineNode> = {}): TimelineNode {
  return {
    node_id: "plot:3",
    anchor_chapter_id: 3,
    progress: 0.3,
    importance_score: 8,
    level: 1,
    summary: "白芷初遇",
    characters: ["白芷"],
    phase_name: "引入期",
    node_type: "plot",
    node_subtype: "plot",
    score_breakdown: { tension: 1.1 },
    plot_flags: {
      is_pivot: false,
      is_cliffhanger: false,
      tension_percentile: 55,
    },
    ...overrides,
  };
}

function createPhases(): TimelinePhase[] {
  return [
    { name: "引入期", start: 1, end: 5, ratio: 0.25 },
    { name: "发展期", start: 6, end: 10, ratio: 0.25 },
    { name: "高潮期", start: 11, end: 15, ratio: 0.25 },
    { name: "收束期", start: 16, end: 20, ratio: 0.25 },
  ];
}

describe("TimelineTrack", () => {
  it("没有节点时会展示空态", () => {
    render(<TimelineTrack nodes={[]} totalChapters={20} />);

    expect(screen.getByText("暂无时间轴节点")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("会渲染节点卡片并把点击事件回传给上层", () => {
    const onNodeClick = vi.fn();
    const node = createNode();

    render(
      <TimelineTrack
        nodes={[node]}
        phases={createPhases()}
        activePhase="引入期"
        selectedNodeId="plot:3"
        onNodeClick={onNodeClick}
        tensionCurve={[0.2, 0.5, 0.8]}
        totalChapters={20}
      />,
    );

    const detailButton = screen.getByText("白芷初遇").closest("button");
    expect(detailButton).not.toBeNull();
    expect(detailButton).toHaveClass("border-primary/35");

    const nodeButton = screen.getByRole("button", { name: "剧情节点: 白芷初遇" });
    expect(nodeButton).toHaveClass("ring-2");

    fireEvent.click(detailButton!);

    expect(onNodeClick).toHaveBeenCalledWith(node);
    expect(screen.getByText("剧情节点")).toBeInTheDocument();
    expect(screen.getByText("第 3 章")).toBeInTheDocument();
    expect(document.querySelector("svg path")).toBeInTheDocument();
  });
});
