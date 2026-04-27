import { createElement } from "react";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Novel, TimelineResponse } from "@/api/types";
import { TimelinePage } from "@/pages/TimelinePage";
import { useNovelStore } from "@/store/novelStore";

const getTimelineMock = vi.fn();
const getNovelMock = vi.fn();
const navigateMock = vi.fn();

let currentTimelineSearchParams = "task_id=task-a&selected_chunk=12&relation_event_id=9002";
let currentTimelineNovelId = "novel-1";

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
  }: {
    onMaxLevelChange: (level: 1 | 2 | 3) => void;
  }) => (
    <div data-testid="timeline-controls">
      <button type="button" onClick={() => onMaxLevelChange(1)}>
        切到重要
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
    nodes: TimelineResponse["nodes"];
    onNodeClick: (node: TimelineResponse["nodes"][number]) => void;
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
    selectedRelationEventId,
    onClose,
  }: {
    node: TimelineResponse["nodes"][number] | null;
    selectedRelationEventId?: number | null;
    onClose?: () => void;
  }) => (
    <div data-testid="timeline-node-detail">
      <span>{node ? `selected-${node.node_id}` : "selected-none"}</span>
      <span>{selectedRelationEventId != null ? `event-${selectedRelationEventId}` : "event-none"}</span>
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

function createTimelineResponse(): TimelineResponse {
  return {
    meta: {
      novel_id: "novel-1",
      novel_name: "Timeline Review Novel",
      total_chunks: 20,
      timeline_contract_version: 2,
    },
    phases: [
      { name: "引入期", start: 1, end: 5, ratio: 0.25 },
      { name: "发展期", start: 6, end: 10, ratio: 0.25 },
      { name: "高潮期", start: 11, end: 15, ratio: 0.25 },
      { name: "收束期", start: 16, end: 20, ratio: 0.25 },
    ],
    nodes: [
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
        node_subtype: "新建",
        score_breakdown: { change_type_weight: 2.4 },
        relation_events: [
          {
            relation_event_id: 9001,
            from_char: "顾承渊",
            to_char: "苏映雪",
            relation_type: "盟友",
            change_type: "新建",
          },
        ],
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
        node_subtype: "断裂",
        score_breakdown: { change_type_weight: 2.6 },
        plot_flags: {
          is_pivot: true,
          is_cliffhanger: false,
          tension_percentile: 90,
        },
        relation_events: [
          {
            relation_event_id: 9002,
            from_char: "顾承渊",
            to_char: "苏映雪",
            relation_type: "盟友",
            change_type: "断裂",
          },
        ],
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
      timeline_contract_version: 2,
    },
    phases: [],
    nodes: [],
    tension_curve: [],
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
    currentTimelineSearchParams = "task_id=task-a&selected_chunk=12&relation_event_id=9002";
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
    currentTimelineSearchParams = "task_id=task-a&selected_chunk=12&relation_event_id=9002";
    useNovelStore.setState({
      currentNovelId: "novel-1",
      currentTaskId: "task-b",
      novelsCache: [],
    });

    renderPage();

    expect(await screen.findByText("selected-relation:9002")).toBeInTheDocument();
    expect(getTimelineMock).toHaveBeenCalledWith("novel-1", "task-a", {
      includeCurve: true,
      maxLevel: 3,
    });
    expect(navigateMock).not.toHaveBeenCalledWith(
      "/novels/novel-1/timeline?task_id=task-b&max_level=3",
      { replace: true }
    );
  });

  it("prefers relation_event_id over selected_chunk when deep-linking from graph", async () => {
    renderPage();

    expect(await screen.findByText("selected-relation:9002")).toBeInTheDocument();
    expect(screen.getByText("event-9002")).toBeInTheDocument();
    expect(screen.queryByText("未定位到指定关系事件，已回退到对应时间节点。")).not.toBeInTheDocument();
  });

  it("falls back to selected_chunk when relation_event_id is missing", async () => {
    currentTimelineSearchParams = "task_id=task-a&selected_chunk=12&relation_event_id=9999";

    renderPage();

    expect(await screen.findByText("selected-relation:9002")).toBeInTheDocument();
    expect(screen.getByText("event-none")).toBeInTheDocument();
    expect(screen.getByText("未定位到指定关系事件，已回退到对应时间节点。")).toBeInTheDocument();
  });

  it("shows a no-match hint without keeping stale selection when neither relation event nor chunk exists", async () => {
    currentTimelineSearchParams = "task_id=task-a&selected_chunk=99&relation_event_id=9999";

    renderPage();

    await screen.findByTestId("timeline-track");
    expect(screen.queryByTestId("timeline-node-detail")).not.toBeInTheDocument();
    expect(screen.getByText("未定位到对应事件。")).toBeInTheDocument();
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
      "/novels/novel-1/timeline?task_id=task-a&max_level=1&selected_node_id=relation%3A9002&selected_chunk=12&relation_event_id=9002",
      { replace: true }
    );

    currentTimelineSearchParams = "task_id=task-a&max_level=1&selected_node_id=relation%3A9002&selected_chunk=12&relation_event_id=9002";
    view.rerender(
      <QueryClientProvider client={view.queryClient}>
        <TimelinePage />
      </QueryClientProvider>
    );
    expect(await screen.findByText("selected-relation:9002")).toBeInTheDocument();
  });

  it("drops a stale relation_event_id when controls change after falling back to selected_chunk", async () => {
    currentTimelineSearchParams = "task_id=task-a&selected_chunk=12&relation_event_id=9999";
    const user = userEvent.setup();

    renderPage();

    await screen.findByText("selected-relation:9002");
    await user.click(screen.getByRole("button", { name: "切到重要" }));

    expect(navigateMock).toHaveBeenLastCalledWith(
      "/novels/novel-1/timeline?task_id=task-a&max_level=1&selected_node_id=relation%3A9002&selected_chunk=12",
      { replace: true }
    );
  });

  it("clears stale relation_event_id after the user manually selects another timeline node", async () => {
    const user = userEvent.setup();

    renderPage();

    await screen.findByText("selected-relation:9002");
    await user.click(screen.getByRole("button", { name: "节点 8" }));

    expect(navigateMock).toHaveBeenLastCalledWith(
      "/novels/novel-1/timeline?task_id=task-a&max_level=3&selected_node_id=relation%3A9001&selected_chunk=8",
      { replace: true }
    );
  });

  it("clears the current deep-link selection when the detail panel is closed", async () => {
    const user = userEvent.setup();

    renderPage();

    await screen.findByText("selected-relation:9002");
    await user.click(screen.getByRole("button", { name: "关闭详情" }));

    expect(navigateMock).toHaveBeenLastCalledWith(
      "/novels/novel-1/timeline?task_id=task-a&max_level=3",
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
        "/novels/novel-1/timeline?task_id=task-b&max_level=3",
        { replace: true }
      );
    });
  });

  it("re-syncs controls and query params when the timeline url changes while mounted", async () => {
    const view = renderPage();

    expect(await screen.findByText("selected-relation:9002")).toBeInTheDocument();
    expect(screen.getByText("tension-on")).toBeInTheDocument();

    currentTimelineSearchParams = "task_id=task-a&max_level=1&selected_chunk=8";
    view.rerender(
      <QueryClientProvider client={view.queryClient}>
        <TimelinePage />
      </QueryClientProvider>
    );

    await waitFor(() => {
      expect(getTimelineMock).toHaveBeenLastCalledWith("novel-1", "task-a", {
        includeCurve: true,
        maxLevel: 1,
      });
    });
    expect(await screen.findByText("selected-relation:9001")).toBeInTheDocument();
    expect(screen.getByText("tension-on")).toBeInTheDocument();
  });
});
