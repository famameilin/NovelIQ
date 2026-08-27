import type { ReactNode } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TimelineNodeDetail } from "@/components/timeline/TimelineNodeDetail";
import type { TimelineEventNode, TimelineEventCausalEdge } from "@/api/types";

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

vi.mock("framer-motion", () => ({
  AnimatePresence: ({ children }: { children?: ReactNode }) => <>{children}</>,
  motion: {
    div: ({ children, ...props }: { children?: ReactNode; [key: string]: unknown }) => <div {...props}>{children}</div>,
  },
}));

function createEventNode(overrides?: Partial<TimelineEventNode>): TimelineEventNode {
  return {
    tree_id: "tree:1",
    root_event_id: "event:1:root",
    title: "少年初入修炼之路",
    summary: "树 1 包含主链 2 环与旁支 1 组，横跨第 1-5 章。",
    anchor_chapter_id: 1,
    anchor_chapter_order: 1,
    start_chapter_id: 1,
    end_chapter_id: 5,
    start_progress: 0.01,
    end_progress: 0.05,
    progress: 0.01,
    chapter_ids: [1, 2, 3, 4, 5],
    char_start: 0,
    char_end: 1200,
    participants: [
      { name: "萧炎", role: "protagonist", entity_id: 1, entity_type: "character" },
      { name: "药老", role: "supporting", entity_id: 2, entity_type: "character" },
    ],
    character_names: ["萧炎", "药老"],
    importance_score: 8.2,
    level: 1,
    phase_name: "引入期",
    main_chain: ["event:1:root", "event:1:main:1"],
    secondary_groups: [{ target_event_id: "event:1:sec:1", branch: ["event:1:sec:1:b1"] }],
    causal_in: 1,
    causal_out: 1,
    node_type: "event",
    ...overrides,
  };
}

function createCausalEdges(): TimelineEventCausalEdge[] {
  const expired = new Date(Date.now() - 86400000).toISOString();
  return [
    {
      edge_id: "causal:external->event:1:root:inactive",
      edge_type: "causal",
      source_event_id: "event:external:root",
      target_event_id: "event:1:root",
      source_chapter_id: 1,
      target_chapter_id: 1,
      is_active: false,
      evidence: [{ kind: "paragraph", paragraph_id: 102, excerpt: "已过期因果" }],
      expired_at: expired,
    },
    {
      edge_id: "causal:event:1:main:1->event:external:2:active",
      edge_type: "causal",
      source_event_id: "event:1:main:1",
      target_event_id: "event:external:2",
      source_chapter_id: 1,
      target_chapter_id: 8,
      is_active: true,
      evidence: [{ kind: "paragraph", paragraph_id: 101, excerpt: "因果证据1" }],
      expired_at: null,
    },
  ];
}

describe("TimelineNodeDetail (event forest)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders participants as dict and shows main_chain", () => {
    const node = createEventNode();
    render(<TimelineNodeDetail node={node} novelId="novel-1" taskId="task-a" causalEdges={[]} />);

    expect(screen.getAllByText("萧炎").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("药老").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/event:1:root/)).toBeInTheDocument();
    expect(screen.getByText(/event:1:main:1/)).toBeInTheDocument();
  });

  it("renders secondary_groups", () => {
    const node = createEventNode();
    render(<TimelineNodeDetail node={node} novelId="novel-1" taskId="task-a" causalEdges={[]} />);

    expect(screen.getAllByText(/event:1:sec:1/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/旁支分支/)).toBeInTheDocument();
  });

  it("renders causal edges and shows inactive with expired_at", () => {
    const node = createEventNode();
    const edges = createCausalEdges();
    render(<TimelineNodeDetail node={node} novelId="novel-1" taskId="task-a" causalEdges={edges} />);

    // 因果边标题包含 入/出 计数
    expect(screen.getByText(/因果边/)).toBeInTheDocument();
    // inactive 徽标与过期时间
    expect(screen.getByText("已失效")).toBeInTheDocument();
    expect(screen.getByText(/失效于/)).toBeInTheDocument();
    expect(document.body.textContent).toContain("event:1:root");
    expect(screen.getByText("活跃")).toBeInTheDocument();
  });

  it("shows jump to evidence with tree_id", async () => {
    const user = userEvent.setup();
    const node = createEventNode();

    render(<TimelineNodeDetail node={node} novelId="novel-1" taskId="task-a" causalEdges={[]} />);

    await user.click(screen.getByRole("button", { name: "查看证据" }));

    expect(navigateMock).toHaveBeenCalledWith(expect.stringContaining("tree%3A1"));
    expect(navigateMock).toHaveBeenCalledWith(expect.stringContaining("/novels/novel-1/timeline"));
    expect(navigateMock).toHaveBeenCalledWith(expect.stringContaining("task_id=task-a"));
  });

  it("handles node without secondary groups", () => {
    const node = createEventNode({ secondary_groups: [] });
    render(<TimelineNodeDetail node={node} novelId="novel-1" taskId="task-a" causalEdges={[]} />);

    expect(screen.getAllByText("萧炎").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/旁支分支.*无/)).toBeInTheDocument();
    expect(screen.getByText("该树暂无旁支")).toBeInTheDocument();
  });
});
