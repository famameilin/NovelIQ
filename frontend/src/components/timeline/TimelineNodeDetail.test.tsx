import type { ReactNode } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { TimelineNodeDetail } from "@/components/timeline/TimelineNodeDetail";
import type { TimelineNode } from "@/api/types";

const navigateMock = vi.fn();

vi.mock("react-router-dom", () => ({
  useNavigate: () => navigateMock,
}));

vi.mock("@/components/ui/button", () => ({
  Button: ({
    children,
    ...props
  }: {
    children?: ReactNode;
    [key: string]: unknown;
  }) => <button {...props}>{children}</button>,
}));

vi.mock("@/components/ui/badge", () => ({
  Badge: ({
    children,
    ...props
  }: {
    children?: ReactNode;
    [key: string]: unknown;
  }) => <span {...props}>{children}</span>,
}));

vi.mock("@/components/ui/card", () => ({
  Card: ({ children, ...props }: { children?: ReactNode; [key: string]: unknown }) => <div {...props}>{children}</div>,
  CardContent: ({ children, ...props }: { children?: ReactNode; [key: string]: unknown }) => <div {...props}>{children}</div>,
  CardHeader: ({ children, ...props }: { children?: ReactNode; [key: string]: unknown }) => <div {...props}>{children}</div>,
  CardTitle: ({ children, ...props }: { children?: ReactNode; [key: string]: unknown }) => <div {...props}>{children}</div>,
}));

vi.mock("framer-motion", () => ({
  AnimatePresence: ({ children }: { children?: ReactNode }) => <>{children}</>,
  motion: {
    div: ({ children, ...props }: { children?: ReactNode; [key: string]: unknown }) => <div {...props}>{children}</div>,
  },
}));

function createRelationNode(): TimelineNode {
  return {
    chunk_id: 12,
    progress: 0.6,
    importance_score: 8,
    level: 1,
    event: "顾承渊与苏映雪关系断裂",
    characters: ["顾承渊", "苏映雪"],
    is_pivot: true,
    is_cliffhanger: false,
    tension_percentile: 90,
    node_type: "relation_change",
    relation_changes: [
      {
        relation_event_id: 9002,
        from_char: "顾承渊",
        to_char: "苏映雪",
        relation_type: "盟友",
        change_type: "断裂",
        evidence: "二人决裂",
        confidence: 0.63,
        directionality: "directed",
      },
    ],
  };
}

function createLifecycleNode(): TimelineNode {
  return {
    chunk_id: 3,
    progress: 0.15,
    importance_score: 6,
    level: 1,
    event: "苏映雪首次登场",
    characters: ["苏映雪"],
    is_pivot: false,
    is_cliffhanger: false,
    tension_percentile: 40,
    node_type: "character_entry",
    character_entries: ["苏映雪"],
  };
}

describe("TimelineNodeDetail", () => {
  it("shows lifecycle guidance for character entry nodes", () => {
    render(
      <TimelineNodeDetail
        node={createLifecycleNode()}
        novelId="novel-1"
        taskId="task-a"
      />
    );

    expect(screen.getByText("这是 timeline 基于稳定 lifecycle 标出的首次登场节点，不是页面侧临时推断结果。")).toBeInTheDocument();
    expect(screen.getAllByText("苏映雪")).toHaveLength(2);
  });

  it("highlights the selected relation event and can jump back to graph", async () => {
    const user = userEvent.setup();

    render(
      <TimelineNodeDetail
        node={createRelationNode()}
        novelId="novel-1"
        taskId="task-a"
        selectedRelationEventId={9002}
      />
    );

    expect(screen.getByText("事件 #9002")).toBeInTheDocument();
    expect(screen.getByText("置信 63%")).toBeInTheDocument();
    expect(screen.getByText("directed")).toBeInTheDocument();
    expect(screen.getByText("二人决裂")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "回到图谱入口" }));

    expect(navigateMock).toHaveBeenCalledWith(
      "/novels/novel-1/graph?task_id=task-a&selected_chunk=12&relation_event_id=9002"
    );
  });
});
