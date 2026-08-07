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

// 2026-08-07 用于构造时间轴节点消费的稳定图谱变化合同
function createRelationGraphChange(changeId = "relation:9002") {
  return {
    change_id: changeId,
    change_kind: "relation" as const,
    graph_version_id: "graph-version-1",
    chapter_id: 2,
    fact_id: `fact:${changeId}`,
    fact_revision: 1,
    effective_chunk_id: 12,
    changes: [{ change_kind: "break" }],
    evidence: [{ reason: "二人决裂", chunk_id: 12 }],
    relation_id: "relation:88",
    relation_version_id: 88,
    relation_revision: 1,
    from_char: "顾承渊",
    to_char: "苏映雪",
    relation_type: "盟友",
    relation_change_kind: "break",
    directionality: "directed" as const,
  };
}

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
    node_subtype: "break",
    score_breakdown: { change_type_weight: 2.6, pair_importance: 1.2 },
    graph_changes: [createRelationGraphChange()],
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

// 2026-08-07 用于验证实体状态变化也可稳定回跳到章节图
function createStateNode(): TimelineNode {
  return {
    node_id: "state:12:9",
    anchor_chunk_id: 9,
    progress: 0.45,
    importance_score: 7,
    level: 1,
    summary: "顾承渊从试探转为结盟",
    characters: ["顾承渊"],
    phase_name: "发展期",
    node_type: "state",
    node_subtype: "state",
    score_breakdown: { state_change_weight: 2.1 },
    graph_changes: [
      {
        change_id: "state:12:9",
        change_kind: "state",
        graph_version_id: "graph-version-1",
        chapter_id: 2,
        fact_id: "fact:state:12:9",
        fact_revision: 1,
        effective_chunk_id: 9,
        changes: [{ field: "status", value: "结盟" }],
        evidence: [{ reason: "顾承渊明确放下戒备", chunk_id: 9 }],
        entity_id: 12,
        entity_name: "顾承渊",
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
    node_subtype: "reinforce",
    score_breakdown: { change_type_weight: 1.8, pair_importance: 1.9 },
    graph_changes: [
      {
        ...createRelationGraphChange("relation:9101"),
        to_char: "苏映雪",
        relation_change_kind: "weaken",
      },
      {
        ...createRelationGraphChange("relation:9102"),
        to_char: "陆沉",
        relation_type: "对手",
        relation_change_kind: "reinforce",
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
    node_subtypes: ["reinforce", "break"],
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

  it("shows a state graph change and can jump back to graph", async () => {
    const user = userEvent.setup();

    render(
      <TimelineNodeDetail
        node={createStateNode()}
        atomicNodes={[createStateNode()]}
        novelId="novel-1"
        taskId="task-a"
        selectedGraphChangeId="state:12:9"
      />,
    );

    expect(screen.getByText("顾承渊状态更新")).toBeInTheDocument();
    expect(screen.getByText("变化 state:12:9")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "回到图谱入口" }));

    expect(navigateMock).toHaveBeenCalledWith(
      "/novels/novel-1/graph?task_id=task-a&selected_chunk=9&change_id=state%3A12%3A9",
    );
  });

  it("highlights the selected graph change and can jump back to graph", async () => {
    const user = userEvent.setup();

    render(
      <TimelineNodeDetail
        node={createRelationNode()}
        atomicNodes={[createRelationNode()]}
        novelId="novel-1"
        taskId="task-a"
        selectedGraphChangeId="relation:9002"
      />,
    );

    expect(screen.getByText("变化 relation:9002")).toBeInTheDocument();
    expect(screen.getByText("directed")).toBeInTheDocument();
    expect(screen.getByText("二人决裂")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "回到图谱入口" }));

    expect(navigateMock).toHaveBeenCalledWith(
      "/novels/novel-1/graph?task_id=task-a&selected_chunk=12&change_id=relation%3A9002",
    );
  });

  it("ignores an external change_id that does not belong to the current node", async () => {
    const user = userEvent.setup();

    render(
      <TimelineNodeDetail
        node={createRelationNode()}
        atomicNodes={[createRelationNode()]}
        novelId="novel-1"
        taskId="task-a"
        selectedGraphChangeId="relation:9101"
      />,
    );

    await user.click(screen.getByRole("button", { name: "回到图谱入口" }));

    expect(navigateMock).toHaveBeenCalledWith(
      "/novels/novel-1/graph?task_id=task-a&selected_chunk=12&change_id=relation%3A9002",
    );
  });

  it("does not send a graph auto-selection when the node contains multiple graph changes", async () => {
    const user = userEvent.setup();

    render(<TimelineNodeDetail node={createMultiRelationNode()} atomicNodes={[createMultiRelationNode()]} novelId="novel-1" taskId="task-a" />);

    await user.click(screen.getByRole("button", { name: "回到图谱入口" }));

    expect(navigateMock).toHaveBeenCalledWith("/novels/novel-1/graph?task_id=task-a");
  });

  it("falls back to the node's only graph change when the url-level selection is absent", async () => {
    const user = userEvent.setup();

    render(<TimelineNodeDetail node={createRelationNode()} atomicNodes={[createRelationNode()]} novelId="novel-1" taskId="task-a" />);

    await user.click(screen.getByRole("button", { name: "回到图谱入口" }));

    expect(navigateMock).toHaveBeenCalledWith(
      "/novels/novel-1/graph?task_id=task-a&selected_chunk=12&change_id=relation%3A9002",
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
      graph_changes: [createRelationGraphChange("relation:9101")],
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
