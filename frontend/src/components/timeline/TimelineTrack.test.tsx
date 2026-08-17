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
    expect(screen.getAllByRole("button")).toHaveLength(1);

    const connector = screen.getByTestId("timeline-connector");
    expect(connector).toHaveAttribute("x1", connector.getAttribute("x2"));

    fireEvent.click(detailButton!);

    expect(onNodeClick).toHaveBeenCalledWith(node);
    expect(screen.getByText("剧情节点")).toBeInTheDocument();
    expect(screen.getByText("第 3 章")).toBeInTheDocument();
    expect(document.querySelector("svg path")).toBeInTheDocument();
    expect(screen.getByTestId("timeline-card")).toBe(detailButton);
  });

  it("按最终进度全局排序，并让奇偶卡严格交替使用第二层和第一层", () => {
    const nodes = [
      createNode({ node_id: "plot:4", anchor_chapter_id: 4, progress: 0.4, summary: "顺序4" }),
      createNode({ node_id: "plot:2", anchor_chapter_id: 2, progress: 0.2, summary: "顺序2" }),
      createNode({ node_id: "plot:1", anchor_chapter_id: 1, progress: 0.1, summary: "顺序1" }),
      createNode({ node_id: "plot:3", anchor_chapter_id: 3, progress: 0.3, summary: "顺序3" }),
    ];

    render(<TimelineTrack nodes={nodes} totalChapters={20} />);

    const cards = screen.getAllByTestId("timeline-card");
    expect(cards).toHaveLength(4);
    expect(cards.map((card) => card.dataset.cardOrder)).toEqual(["1", "2", "3", "4"]);
    expect(cards.map((card) => Number(card.dataset.lane))).toEqual([2, 1, 2, -1]);
    expect(screen.getAllByRole("button")).toHaveLength(4);

    cards.forEach((card, index) => {
      expect(card).toHaveTextContent(`顺序${index + 1}`);
      if (index > 0) {
        expect(Number.parseFloat(card.style.left)).toBeGreaterThan(
          Number.parseFloat(cards[index - 1]?.style.left ?? "0"),
        );
      }
    });

    screen.getAllByTestId("timeline-connector").forEach((connector) => {
      expect(connector).toHaveAttribute("x1", connector.getAttribute("x2"));
    });
  });
});
