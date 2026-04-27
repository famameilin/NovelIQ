import type { ReactNode } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TimelineNodeDetail } from "@/components/timeline/TimelineNodeDetail";
import type { TimelineCompositeNode, TimelineNode } from "@/api/types";

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

function createRelationNode(): TimelineNode {
  return {
    node_id: "relation:9002",
    anchor_chunk_id: 12,
    progress: 0.6,
    importance_score: 8,
    level: 1,
    summary: "顾承渊与苏映雪关系断裂",
    characters: ["顾承渊", "苏映雪"],
    phase_name: "高潮期",
    node_type: "relation",
    node_subtype: "断裂",
    score_breakdown: { change_type_weight: 2.6, pair_importance: 1.2 },
    relation_events: [
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
    node_id: "lifecycle:entry:2:3",
    anchor_chunk_id: 3,
    progress: 0.15,
    importance_score: 6,
    level: 1,
    summary: "苏映雪首次登场",
    characters: ["苏映雪"],
    phase_name: "引入期",
    node_type: "lifecycle",
    node_subtype: "entry",
    score_breakdown: { character_importance: 2.2, entry_exit_bonus: 1.4 },
    lifecycle_events: [
      {
        entity_id: 2,
        character_name: "苏映雪",
        lifecycle_type: "entry",
      },
    ],
  };
}

function createMultiRelationNode(): TimelineNode {
  return {
    node_id: "relation:multi",
    anchor_chunk_id: 18,
    progress: 0.9,
    importance_score: 9,
    level: 1,
    summary: "多条关系同时变化",
    characters: ["顾承渊", "苏映雪", "陆沉"],
    phase_name: "收束期",
    node_type: "relation",
    node_subtype: "强化",
    score_breakdown: { change_type_weight: 1.8, pair_importance: 1.9 },
    relation_events: [
      {
        relation_event_id: 9101,
        from_char: "顾承渊",
        to_char: "苏映雪",
        relation_type: "盟友",
        change_type: "弱化",
      },
      {
        relation_event_id: 9102,
        from_char: "顾承渊",
        to_char: "陆沉",
        relation_type: "对手",
        change_type: "强化",
      },
    ],
  };
}

function createCompositeRelationNode(): TimelineCompositeNode {
  return {
    node_id: "composite:relation:12:0",
    anchor_chunk_id: 12,
    start_chunk_id: 12,
    end_chunk_id: 13,
    progress: 0.6,
    start_progress: 0.6,
    end_progress: 0.7,
    importance_score: 8.5,
    level: 1,
    summary: "顾承渊与苏映雪关系连续恶化",
    characters: ["顾承渊", "苏映雪"],
    phase_name: "高潮期",
    node_type: "relation",
    node_subtypes: ["强化", "断裂"],
    representative_node_id: "relation:9002",
    child_node_ids: ["relation:9002", "relation:9101"],
  };
}

describe("TimelineNodeDetail", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows lifecycle guidance for lifecycle entry nodes", () => {
    render(<TimelineNodeDetail node={createLifecycleNode()} atomicNodes={[createLifecycleNode()]} novelId="novel-1" taskId="task-a" />);

    expect(screen.getByText("这里表达的是 authority lifecycle 的稳定事件，不是页面侧临时推断结果。")).toBeInTheDocument();
    expect(screen.getAllByText("苏映雪").length).toBeGreaterThanOrEqual(2);
  });

  it("does not send a chunk-only graph selection for lifecycle nodes", async () => {
    const user = userEvent.setup();

    render(<TimelineNodeDetail node={createLifecycleNode()} atomicNodes={[createLifecycleNode()]} novelId="novel-1" taskId="task-a" />);

    await user.click(screen.getByRole("button", { name: "回到图谱入口" }));

    expect(navigateMock).toHaveBeenCalledWith("/novels/novel-1/graph?task_id=task-a");
  });

  it("highlights the selected relation event and can jump back to graph", async () => {
    const user = userEvent.setup();

    render(
      <TimelineNodeDetail
        node={createRelationNode()}
        atomicNodes={[createRelationNode()]}
        novelId="novel-1"
        taskId="task-a"
        selectedRelationEventId={9002}
      />,
    );

    expect(screen.getByText("事件 #9002")).toBeInTheDocument();
    expect(screen.getByText("置信 63%")).toBeInTheDocument();
    expect(screen.getByText("directed")).toBeInTheDocument();
    expect(screen.getByText("二人决裂")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "回到图谱入口" }));

    expect(navigateMock).toHaveBeenCalledWith(
      "/novels/novel-1/graph?task_id=task-a&selected_chunk=12&relation_event_id=9002",
    );
  });

  it("ignores an external relation_event_id that does not belong to the current node", async () => {
    const user = userEvent.setup();

    render(
      <TimelineNodeDetail
        node={createRelationNode()}
        atomicNodes={[createRelationNode()]}
        novelId="novel-1"
        taskId="task-a"
        selectedRelationEventId={9101}
      />,
    );

    await user.click(screen.getByRole("button", { name: "回到图谱入口" }));

    expect(navigateMock).toHaveBeenCalledWith(
      "/novels/novel-1/graph?task_id=task-a&selected_chunk=12&relation_event_id=9002",
    );
  });

  it("does not send a graph auto-selection when the node contains multiple relation events", async () => {
    const user = userEvent.setup();

    render(<TimelineNodeDetail node={createMultiRelationNode()} atomicNodes={[createMultiRelationNode()]} novelId="novel-1" taskId="task-a" />);

    await user.click(screen.getByRole("button", { name: "回到图谱入口" }));

    expect(navigateMock).toHaveBeenCalledWith("/novels/novel-1/graph?task_id=task-a");
  });

  it("falls back to the node's only relation event when the url-level selection is absent", async () => {
    const user = userEvent.setup();

    render(<TimelineNodeDetail node={createRelationNode()} atomicNodes={[createRelationNode()]} novelId="novel-1" taskId="task-a" />);

    await user.click(screen.getByRole("button", { name: "回到图谱入口" }));

    expect(navigateMock).toHaveBeenCalledWith(
      "/novels/novel-1/graph?task_id=task-a&selected_chunk=12&relation_event_id=9002",
    );
  });

  it("shows composite child nodes and does not construct a fuzzy graph selection", async () => {
    const user = userEvent.setup();
    const onSelectAtomicNode = vi.fn();
    const firstAtomicNode = createRelationNode();
    const secondAtomicNode: TimelineNode = {
      ...createRelationNode(),
      node_id: "relation:9101",
      anchor_chunk_id: 13,
      relation_events: [
        {
          relation_event_id: 9101,
          from_char: "顾承渊",
          to_char: "苏映雪",
          relation_type: "盟友",
          change_type: "强化",
        },
      ],
    };

    render(
      <TimelineNodeDetail
        node={createCompositeRelationNode()}
        atomicNodes={[firstAtomicNode, secondAtomicNode]}
        novelId="novel-1"
        taskId="task-a"
        onSelectAtomicNode={onSelectAtomicNode}
      />,
    );

    expect(screen.getByText("复合节点包含的原子节点")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "回到图谱入口" }));
    expect(navigateMock).toHaveBeenCalledWith("/novels/novel-1/graph?task_id=task-a");

    await user.click(screen.getAllByRole("button", { name: "查看原子节点" })[0]!);
    expect(onSelectAtomicNode).toHaveBeenCalledWith(firstAtomicNode);
  });
});
