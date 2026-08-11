import { createElement } from "react";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Novel, TimelineCompositeNode, TimelineNode, TimelineResponse } from "@/api/types";
import { TimelinePage } from "@/pages/TimelinePage";
import { useNovelStore } from "@/store/novelStore";

const getTimelineMock = vi.fn();
const getNovelMock = vi.fn();
const navigateMock = vi.fn();

let currentTimelineSearchParams = "task_id=task-a&selected_chunk=12&change_id=relation%3A9002";
let currentTimelineNovelId = "novel-1";
type TimelineDisplayNode = TimelineNode | TimelineCompositeNode;

function passthroughComponent(displayName: string) {
  const Component = ({ children }: { children?: ReactNode }) => <div data-testid={displayName}>{children}</div>;
  Component.displayName = displayName;
  return Component;
}

function motionElement(tagName: string) {
  const Component = (props: {
    children?: ReactNode;
    whileHover?: unknown;
    transition?: unknown;
    variants?: unknown;
    initial?: unknown;
    animate?: unknown;
    exit?: unknown;
    [key: string]: unknown;
  }) => {
    const sanitizedProps = { ...props };
    delete sanitizedProps.whileHover;
    delete sanitizedProps.transition;
    delete sanitizedProps.variants;
    delete sanitizedProps.initial;
    delete sanitizedProps.animate;
    delete sanitizedProps.exit;
    delete sanitizedProps.whileTap;
    return createElement(tagName, sanitizedProps, props.children);
  };
  Component.displayName = `motion-${tagName}`;
  return Component;
}

vi.mock("react-router-dom", () => ({
  useNavigate: () => navigateMock,
  useParams: () => ({ novelId: currentTimelineNovelId }),
  useSearchParams: () => [new URLSearchParams(currentTimelineSearchParams)],
}));

vi.mock("framer-motion", () => ({
  motion: new Proxy(
    {},
    {
      get: (_target, key: string) => motionElement(key),
    },
  ),
}));

vi.mock("@/components/layout/PageContainer", () => ({
  PageContainer: passthroughComponent("page-container"),
}));

vi.mock("@/components/common/NovelHeader", () => ({
  NovelHeader: ({ title }: { title: string }) => <div>{title}</div>,
}));

vi.mock("@/components/common/MetricCard", () => ({
  MetricCard: ({
    label,
    value,
    footer,
  }: {
    label: string;
    value: number;
    footer?: ReactNode;
  }) => (
    <div data-testid={`metric-card-${label.toLowerCase()}`}>
      <span>{label}</span>
      <span>{value}</span>
      {footer}
    </div>
  ),
}));

vi.mock("@/components/timeline", () => ({
  TimelineControls: ({
    onMaxLevelChange,
    onViewModeChange,
  }: {
    onMaxLevelChange: (level: 1 | 2 | 3) => void;
    onViewModeChange: (view: "composite" | "atomic") => void;
  }) => (
    <div data-testid="timeline-controls">
      <button type="button" onClick={() => onMaxLevelChange(1)}>
        切到重要
      </button>
      <button type="button" onClick={() => onViewModeChange("atomic")}>
        切到原子
      </button>
    </div>
  ),
  PhaseBar: passthroughComponent("phase-bar"),
  TimelineLegend: passthroughComponent("timeline-legend"),
  TensionOverlay: passthroughComponent("tension-overlay"),
  TimelineTrack: ({
    nodes,
    onNodeClick,
    showTension,
  }: {
    nodes: TimelineDisplayNode[];
    onNodeClick: (node: TimelineDisplayNode) => void;
    showTension?: boolean;
  }) => (
    <div data-testid="timeline-track">
      <span>{showTension ? "tension-on" : "tension-off"}</span>
      {nodes.map((node) => (
        <button key={node.node_id} type="button" onClick={() => onNodeClick(node)}>
          节点 {node.anchor_chunk_id}
        </button>
      ))}
    </div>
  ),
  TimelineNodeDetail: ({
    node,
    selectedGraphChangeId,
    atomicNodes,
    onSelectAtomicNode,
    onClose,
  }: {
    node: TimelineDisplayNode | null;
    selectedGraphChangeId?: string | null;
    atomicNodes?: TimelineNode[];
    onSelectAtomicNode?: (node: TimelineNode) => void;
    onClose?: () => void;
  }) => (
    <div data-testid="timeline-node-detail">
      <span>{node ? `selected-${node.node_id}` : "selected-none"}</span>
      <span>{selectedGraphChangeId != null ? `change-${selectedGraphChangeId}` : "change-none"}</span>
      <span>{atomicNodes?.length != null ? `atomic-count-${atomicNodes.length}` : "atomic-count-none"}</span>
      <button type="button" onClick={() => atomicNodes?.[0] && onSelectAtomicNode?.(atomicNodes[0])}>
        选择第一个原子节点
      </button>
      <button type="button" onClick={onClose}>
        关闭详情
      </button>
    </div>
  ),
}));

vi.mock("@/api/results", () => ({
  getTimeline: (...args: unknown[]) => getTimelineMock(...args),
}));

vi.mock("@/api/novels", () => ({
  getNovel: (...args: unknown[]) => getNovelMock(...args),
}));

function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });
}

function createNovel(): Novel {
  return {
    novel_id: "novel-1",
    title: "Timeline Review Novel",
    filename: "timeline.txt",
    author: "Tester",
    upload_time: "2026-04-15T00:00:00Z",
    file_size: 1,
  };
}

// 2026-08-07 用于构造时间轴节点消费的稳定图谱变化合同
function createRelationGraphChange(changeId: string, relationChangeKind: "assert" | "break") {
  return {
    change_id: changeId,
    change_kind: "relation" as const,
    graph_version_id: "graph-version-1",
    chapter_id: 2,
    fact_id: `fact:${changeId}`,
    fact_revision: 1,
    effective_chunk_id: changeId === "relation:9001" ? 8 : 12,
    changes: [{ change_kind: relationChangeKind }],
    relation_id: `relation:${changeId}`,
    relation_version_id: changeId === "relation:9001" ? 9001 : 9002,
    relation_revision: 1,
    from_char: "顾承渊",
    to_char: "苏映雪",
    relation_type: "盟友",
    relation_change_kind: relationChangeKind,
    directionality: "directed" as const,
  };
}

function createTimelineResponse(): TimelineResponse {
  return {
    meta: {
      novel_id: "novel-1",
      novel_name: "Timeline Review Novel",
      total_chunks: 20,
    },
    phases: [
      { name: "引入期", start: 1, end: 5, ratio: 0.25 },
      { name: "发展期", start: 6, end: 10, ratio: 0.25 },
      { name: "高潮期", start: 11, end: 15, ratio: 0.25 },
      { name: "收束期", start: 16, end: 20, ratio: 0.25 },
    ],
    composite_nodes: [
      {
        node_id: "composite:relation:8:0",
        anchor_chunk_id: 8,
        start_chunk_id: 8,
        end_chunk_id: 8,
        progress: 0.4,
        start_progress: 0.4,
        end_progress: 0.4,
        importance_score: 5,
        level: 2,
        summary: "关系变化 A",
        characters: ["顾承渊", "苏映雪"],
        phase_name: "发展期",
        node_type: "relation",
        node_subtypes: ["assert"],
        representative_node_id: "relation:9001",
        child_node_ids: ["relation:9001"],
      },
      {
        node_id: "composite:relation:12:0",
        anchor_chunk_id: 12,
        start_chunk_id: 12,
        end_chunk_id: 12,
        progress: 0.6,
        start_progress: 0.6,
        end_progress: 0.6,
        importance_score: 8,
        level: 1,
        summary: "关系变化 B",
        characters: ["顾承渊", "苏映雪"],
        phase_name: "高潮期",
        node_type: "relation",
        node_subtypes: ["break"],
        representative_node_id: "relation:9002",
        child_node_ids: ["relation:9002"],
      },
    ],
    atomic_nodes: [
      {
        node_id: "relation:9001",
        anchor_chunk_id: 8,
        progress: 0.4,
        importance_score: 5,
        level: 2,
        summary: "关系变化 A",
        characters: ["顾承渊", "苏映雪"],
        phase_name: "发展期",
        node_type: "relation",
        node_subtype: "assert",
        score_breakdown: { change_type_weight: 2.4 },
        graph_changes: [createRelationGraphChange("relation:9001", "assert")],
      },
      {
        node_id: "relation:9002",
        anchor_chunk_id: 12,
        progress: 0.6,
        importance_score: 8,
        level: 1,
        summary: "关系变化 B",
        characters: ["顾承渊", "苏映雪"],
        phase_name: "高潮期",
        node_type: "relation",
        node_subtype: "break",
        score_breakdown: { change_type_weight: 2.6 },
        plot_flags: {
          is_pivot: true,
          is_cliffhanger: false,
          tension_percentile: 90,
        },
        graph_changes: [createRelationGraphChange("relation:9002", "break")],
      },
    ],
    tension_curve: [0.2, 0.4, 0.8],
  };
}

function createEmptyTimelineResponse(): TimelineResponse {
  return {
    meta: {
      novel_id: "novel-1",
      novel_name: "Timeline Review Novel",
      total_chunks: 0,
    },
    phases: [],
    composite_nodes: [],
    atomic_nodes: [],
    tension_curve: [],
  };
}

// 2026-08-07 用于验证实体状态变化可由 change_id 精确定位
function createStateTimelineResponse(): TimelineResponse {
  return {
    ...createTimelineResponse(),
    composite_nodes: [
      ...createTimelineResponse().composite_nodes,
      {
        node_id: "composite:state:9:0",
        anchor_chunk_id: 9,
        start_chunk_id: 9,
        end_chunk_id: 9,
        progress: 0.45,
        start_progress: 0.45,
        end_progress: 0.45,
        importance_score: 7,
        level: 1,
        summary: "顾承渊状态更新",
        characters: ["顾承渊"],
        phase_name: "发展期",
        node_type: "state",
        node_subtypes: ["state"],
        representative_node_id: "state:12:9",
        child_node_ids: ["state:12:9"],
      },
    ],
    atomic_nodes: [
      ...createTimelineResponse().atomic_nodes,
      {
        node_id: "state:12:9",
        anchor_chunk_id: 9,
        progress: 0.45,
        importance_score: 7,
        level: 1,
        summary: "顾承渊状态更新",
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
            entity_id: 12,
            entity_name: "顾承渊",
          },
        ],
      },
    ],
  };
}

function createAmbiguousChunkTimelineResponse(): TimelineResponse {
  return {
    ...createTimelineResponse(),
    composite_nodes: [
      ...createTimelineResponse().composite_nodes,
      {
        node_id: "composite:plot:12:1",
        anchor_chunk_id: 12,
        start_chunk_id: 12,
        end_chunk_id: 12,
        progress: 0.6,
        start_progress: 0.6,
        end_progress: 0.6,
        importance_score: 6,
        level: 2,
        summary: "第十二块的剧情节点",
        characters: ["顾承渊"],
        phase_name: "高潮期",
        node_type: "plot",
        node_subtypes: ["plot"],
        representative_node_id: "plot:12",
        child_node_ids: ["plot:12"],
      },
    ],
    atomic_nodes: [
      ...createTimelineResponse().atomic_nodes,
      {
        node_id: "plot:12",
        anchor_chunk_id: 12,
        progress: 0.6,
        importance_score: 6,
        level: 2,
        summary: "第十二块的剧情节点",
        characters: ["顾承渊"],
        phase_name: "高潮期",
        node_type: "plot",
        node_subtype: "plot",
        score_breakdown: { tension: 1.4 },
        plot_flags: {
          is_pivot: false,
          is_cliffhanger: true,
          tension_percentile: 88,
        },
      },
    ],
  };
}

function renderPage() {
  const queryClient = createQueryClient();
  const view = render(
    <QueryClientProvider client={queryClient}>
      <TimelinePage />
    </QueryClientProvider>
  );
  return { queryClient, ...view };
}

describe("TimelinePage deep links", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    currentTimelineSearchParams = "task_id=task-a&selected_chunk=12&change_id=relation%3A9002";
    currentTimelineNovelId = "novel-1";
    useNovelStore.setState({
      currentNovelId: null,
      currentTaskId: "task-a",
      novelsCache: [],
    });
    getNovelMock.mockResolvedValue(createNovel());
    getTimelineMock.mockResolvedValue(createTimelineResponse());
  });

  it("shows the no-task state when no task is selected", async () => {
    currentTimelineSearchParams = "";
    useNovelStore.setState({
      currentNovelId: null,
      currentTaskId: null,
      novelsCache: [],
    });

    renderPage();

    expect(await screen.findByText("请先选择分析任务")).toBeInTheDocument();
    expect(getTimelineMock).not.toHaveBeenCalled();
  });

  it("shows the missing-novel state when the route param is absent", async () => {
    currentTimelineNovelId = undefined as unknown as string;

    renderPage();

    expect(await screen.findByText("小说不存在")).toBeInTheDocument();
    expect(getTimelineMock).not.toHaveBeenCalled();
    expect(getNovelMock).not.toHaveBeenCalled();
  });

  it("keeps the URL deep-link task authoritative when the store still holds an older task", async () => {
    currentTimelineSearchParams = "task_id=task-a&selected_chunk=12&change_id=relation%3A9002";
    useNovelStore.setState({
      currentNovelId: "novel-1",
      currentTaskId: "task-b",
      novelsCache: [],
    });

    renderPage();

    expect(await screen.findByText("selected-relation:9002")).toBeInTheDocument();
    expect(getTimelineMock).toHaveBeenCalledWith("novel-1", "task-a", {
      includeCurve: true,
    });
    expect(navigateMock).not.toHaveBeenCalledWith(
      "/novels/novel-1/timeline?task_id=task-b&max_level=3&view=composite",
      { replace: true }
    );
  });

  it("prefers change_id over selected_chunk when deep-linking from graph", async () => {
    renderPage();

    expect(await screen.findByText("selected-relation:9002")).toBeInTheDocument();
    expect(screen.getByText("change-relation:9002")).toBeInTheDocument();
    expect(screen.queryByText("未定位到指定图谱变化，已回退到对应时间节点。")).not.toBeInTheDocument();
  });

  it("selects a state node by its stable change_id", async () => {
    currentTimelineSearchParams = "task_id=task-a&selected_chunk=9&change_id=state%3A12%3A9";
    getTimelineMock.mockResolvedValue(createStateTimelineResponse());

    renderPage();

    expect(await screen.findByText("selected-state:12:9")).toBeInTheDocument();
    expect(screen.getByText("change-state:12:9")).toBeInTheDocument();
  });

  it("prefers selected_node_id over a conflicting change_id and drops the stale change binding", async () => {
    currentTimelineSearchParams = "task_id=task-a&selected_node_id=relation%3A9001&selected_chunk=8&change_id=relation%3A9002";
    const user = userEvent.setup();

    renderPage();

    expect(await screen.findByText("selected-relation:9001")).toBeInTheDocument();
    expect(screen.getByText("change-none")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "切到重要" }));

    expect(navigateMock).toHaveBeenLastCalledWith(
      "/novels/novel-1/timeline?task_id=task-a&max_level=1&view=composite&selected_node_id=relation%3A9001&selected_chunk=8",
      { replace: true }
    );
  });

  it("falls back to selected_chunk when change_id is missing", async () => {
    currentTimelineSearchParams = "task_id=task-a&selected_chunk=12&change_id=relation%3A9999";

    renderPage();

    expect(await screen.findByText("selected-composite:relation:12:0")).toBeInTheDocument();
    expect(screen.getByText("change-none")).toBeInTheDocument();
    expect(screen.getByText("未定位到指定图谱变化，已回退到对应时间节点。")).toBeInTheDocument();
  });

  it("does not guess a node when selected_chunk maps to multiple timeline nodes", async () => {
    currentTimelineSearchParams = "task_id=task-a&selected_chunk=12";
    getTimelineMock.mockResolvedValue(createAmbiguousChunkTimelineResponse());

    renderPage();

    await screen.findByTestId("timeline-track");
    expect(screen.queryByTestId("timeline-node-detail")).not.toBeInTheDocument();
    expect(screen.getByText("该时间块包含多个不同类型节点，请使用稳定节点链接重新定位。")).toBeInTheDocument();
  });

  it("shows a no-match hint without keeping stale selection when neither graph change nor chunk exists", async () => {
    currentTimelineSearchParams = "task_id=task-a&selected_chunk=99&change_id=relation%3A9999";

    renderPage();

    await screen.findByTestId("timeline-track");
    expect(screen.queryByTestId("timeline-node-detail")).not.toBeInTheDocument();
    expect(screen.getByText("未定位到对应图谱变化。")).toBeInTheDocument();
  });

  it("shows explicit empty states for missing phases and nodes", async () => {
    getTimelineMock.mockResolvedValue(createEmptyTimelineResponse());

    renderPage();

    expect(await screen.findByText("暂无阶段数据")).toBeInTheDocument();
    expect(screen.getByText("暂无时间轴节点")).toBeInTheDocument();
  });

  it("shows the error state and supports retry", async () => {
    getTimelineMock.mockRejectedValueOnce(new Error("boom")).mockResolvedValueOnce(createTimelineResponse());

    renderPage();

    expect(await screen.findByText("加载失败")).toBeInTheDocument();
    const retryButtons = await screen.findAllByRole("button", { name: /重试/ });
    retryButtons[0]?.click();

    await waitFor(() => {
      expect(getTimelineMock).toHaveBeenCalledTimes(2);
    });
    expect(await screen.findByText("selected-relation:9002")).toBeInTheDocument();
  });

  it("keeps the graph deep-link selection when timeline controls change", async () => {
    const user = userEvent.setup();
    const view = renderPage();

    await screen.findByText("selected-relation:9002");
    await user.click(screen.getByRole("button", { name: "切到重要" }));
    expect(navigateMock).toHaveBeenLastCalledWith(
      "/novels/novel-1/timeline?task_id=task-a&max_level=1&view=composite&selected_node_id=relation%3A9002&selected_chunk=12&change_id=relation%3A9002",
      { replace: true }
    );

    currentTimelineSearchParams = "task_id=task-a&max_level=1&view=composite&selected_node_id=relation%3A9002&selected_chunk=12&change_id=relation%3A9002";
    view.rerender(
      <QueryClientProvider client={view.queryClient}>
        <TimelinePage />
      </QueryClientProvider>
    );
    expect(await screen.findByText("selected-relation:9002")).toBeInTheDocument();
  });

  it("drops a stale change_id when controls change after falling back to selected_chunk", async () => {
    currentTimelineSearchParams = "task_id=task-a&selected_chunk=12&change_id=relation%3A9999";
    const user = userEvent.setup();

    renderPage();

    await screen.findByText("selected-composite:relation:12:0");
    await user.click(screen.getByRole("button", { name: "切到重要" }));

    expect(navigateMock).toHaveBeenLastCalledWith(
      "/novels/novel-1/timeline?task_id=task-a&max_level=1&view=composite&selected_node_id=composite%3Arelation%3A12%3A0&selected_chunk=12",
      { replace: true }
    );
  });

  it("clears stale change_id after the user manually selects another timeline node", async () => {
    const user = userEvent.setup();

    renderPage();

    await screen.findByText("selected-relation:9002");
    await user.click(screen.getByRole("button", { name: "节点 8" }));

    expect(navigateMock).toHaveBeenLastCalledWith(
      "/novels/novel-1/timeline?task_id=task-a&max_level=3&view=composite&selected_node_id=composite%3Arelation%3A8%3A0&selected_chunk=8",
      { replace: true }
    );
  });

  it("clears the current deep-link selection when the detail panel is closed", async () => {
    const user = userEvent.setup();

    renderPage();

    await screen.findByText("selected-relation:9002");
    await user.click(screen.getByRole("button", { name: "关闭详情" }));

    expect(navigateMock).toHaveBeenLastCalledWith(
      "/novels/novel-1/timeline?task_id=task-a&max_level=3&view=composite",
      { replace: true }
    );
  });

  it("clears deep-link selection when switching to another task", async () => {
    renderPage();

    await screen.findByText("selected-relation:9002");
    useNovelStore.setState({
      currentNovelId: "novel-1",
      currentTaskId: "task-b",
      novelsCache: [],
    });

    await waitFor(() => {
      expect(navigateMock).toHaveBeenCalledWith(
        "/novels/novel-1/timeline?task_id=task-b&max_level=3&view=composite",
        { replace: true }
      );
    });
  });

  it("re-syncs local controls without refetching timeline data when only display params change", async () => {
    const view = renderPage();

    expect(await screen.findByText("selected-relation:9002")).toBeInTheDocument();
    expect(screen.getByText("tension-on")).toBeInTheDocument();
    expect(getTimelineMock).toHaveBeenCalledTimes(1);

    currentTimelineSearchParams = "task_id=task-a&max_level=3&view=atomic&selected_node_id=relation%3A9001&selected_chunk=8";
    view.rerender(
      <QueryClientProvider client={view.queryClient}>
        <TimelinePage />
      </QueryClientProvider>
    );

    await waitFor(() => {
      expect(getTimelineMock).toHaveBeenCalledTimes(1);
    });
    expect(await screen.findByText("selected-relation:9001")).toBeInTheDocument();
    expect(screen.getByText("tension-on")).toBeInTheDocument();
  });
});
