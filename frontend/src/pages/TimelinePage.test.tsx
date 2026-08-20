import { createElement } from "react";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Novel, TimelineEventNode, EventTimelineResponse } from "@/api/types";
import { TimelinePage } from "@/pages/TimelinePage";
import { useNovelStore } from "@/store/novelStore";
import { createEventTimeline } from "@/mocks/data";

const getTimelineMock = vi.fn();
const getNovelMock = vi.fn();
const navigateMock = vi.fn();

let currentTimelineSearchParams = "task_id=task-a&tree_id=tree%3A1";
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
      <button type="button" onClick={() => onMaxLevelChange(3)}>
        切到全部
      </button>
    </div>
  ),
  PhaseBar: passthroughComponent("phase-bar"),
  TimelineLegend: passthroughComponent("timeline-legend"),
  TensionOverlay: passthroughComponent("tension-overlay"),
  TimelineTrack: ({
    nodes,
    onNodeClick,
  }: {
    nodes: TimelineEventNode[];
    onNodeClick: (node: TimelineEventNode) => void;
  }) => (
    <div data-testid="timeline-track">
      {nodes.map((node) => (
        <button key={node.tree_id} type="button" onClick={() => onNodeClick(node)}>
          节点 {node.tree_id}
        </button>
      ))}
    </div>
  ),
  TimelineNodeDetail: ({
    node,
    onClose,
  }: {
    node: TimelineEventNode | null;
    onClose?: () => void;
  }) => (
    <div data-testid="timeline-node-detail">
      <span>{node ? `selected-${node.tree_id}` : "selected-none"}</span>
      <span>{node?.participants?.[0] ? `participant-${node.participants[0].name}` : "participant-none"}</span>
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

function renderPage() {
  const queryClient = createQueryClient();
  const view = render(
    <QueryClientProvider client={queryClient}>
      <TimelinePage />
    </QueryClientProvider>
  );
  return { queryClient, ...view };
}

function createEmptyEventTimelineResponse(totalChapters: number): EventTimelineResponse {
  const base = createEventTimeline();
  return {
    ...base,
    meta: { ...base.meta, total_chapters: totalChapters, novel_id: "novel-1", novel_name: "Timeline Review Novel" },
    nodes: [],
    causal_edges: [],
    foreshadowing_edges: [],
    derived_event_order: [],
    tension_curve: base.tension_curve,
    phases: totalChapters === 0 ? [] : base.phases,
    total_chapters: totalChapters,
  };
}

describe("TimelinePage deep links (event forest)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    currentTimelineSearchParams = "task_id=task-a&tree_id=tree%3A1";
    currentTimelineNovelId = "novel-1";
    useNovelStore.setState({
      currentNovelId: null,
      currentTaskId: "task-a",
      novelsCache: [],
    });
    getNovelMock.mockResolvedValue(createNovel());
    getTimelineMock.mockResolvedValue(createEventTimeline());
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
    currentTimelineSearchParams = "task_id=task-a&tree_id=tree%3A1";
    useNovelStore.setState({
      currentNovelId: "novel-1",
      currentTaskId: "task-b",
      novelsCache: [],
    });

    renderPage();

    expect(await screen.findByText("selected-tree:1")).toBeInTheDocument();
    expect(getTimelineMock).toHaveBeenCalledWith("novel-1", "task-a", {
      includeCurve: true,
    });
    expect(navigateMock).not.toHaveBeenCalledWith(
      expect.stringContaining("task_id=task-b"),
      expect.anything()
    );
  });

  it("selects node by tree_id deep link and keeps participants dict", async () => {
    const timeline = createEventTimeline();
    getTimelineMock.mockResolvedValue(timeline);
    const first = timeline.nodes[0];
    currentTimelineSearchParams = `task_id=task-a&tree_id=${encodeURIComponent(first!.tree_id)}`;

    renderPage();

    expect(await screen.findByText(`selected-${first!.tree_id}`)).toBeInTheDocument();
    expect(screen.getByText(`participant-${first!.participants[0]!.name}`)).toBeInTheDocument();
  });

  it("displayNodes are sorted by derivedOrder", async () => {
    const timeline = createEventTimeline();
    // shuffle nodes order to ensure sorting by derivedEventOrder is enforced
    const shuffled = [...timeline.nodes].sort(() => Math.random() - 0.5);
    getTimelineMock.mockResolvedValue({ ...timeline, nodes: shuffled });
    currentTimelineSearchParams = "task_id=task-a";

    renderPage();

    await screen.findByTestId("timeline-track");
    const buttons = screen.getAllByRole("button", { name: /节点 tree:/ });
    const orderInDom = buttons.map((b) => b.textContent?.replace("节点 ", "") ?? "");
    // derived_event_order 仅含 event_id，需经 root_event_id 映射到 tree_id 再比较
    const rootToTree = new Map(timeline.nodes.map((n) => [n.root_event_id, n.tree_id]));
    const expectedTreeOrder = timeline.derived_event_order
      .map((eid) => rootToTree.get(eid))
      .filter((tid): tid is string => Boolean(tid && orderInDom.includes(tid)));
    expect(orderInDom).toEqual(expectedTreeOrder.slice(0, orderInDom.length));
  });

  it("shows historic empty state with re-analyze button when total_chapters===0 and nodes empty", async () => {
    getTimelineMock.mockResolvedValue(createEmptyEventTimelineResponse(0));

    renderPage();

    expect(await screen.findByText("该任务为历史版本，无事件森林数据，请重新分析")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /重新分析/ })).toBeInTheDocument();
  });

  it("shows generic empty state when nodes empty but chapters exist", async () => {
    getTimelineMock.mockResolvedValue(createEmptyEventTimelineResponse(120));

    renderPage();

    expect(await screen.findByText("暂无时间轴节点")).toBeInTheDocument();
    expect(screen.queryByText("该任务为历史版本，无事件森林数据，请重新分析")).not.toBeInTheDocument();
  });

  it("filters nodes by maxLevel", async () => {
    const timeline = createEventTimeline();
    getTimelineMock.mockResolvedValue(timeline);
    currentTimelineSearchParams = "task_id=task-a&max_level=1";
    const user = userEvent.setup();

    const view = renderPage();
    await screen.findByTestId("timeline-track");
    const level1Count = timeline.nodes.filter((n) => n.level <= 1).length;
    expect(screen.getAllByRole("button", { name: /节点 tree:/ })).toHaveLength(level1Count);

    // toggle back to all via controls
    await user.click(screen.getByRole("button", { name: "切到全部" }));
    expect(navigateMock).toHaveBeenCalledWith(
      expect.stringContaining("max_level=3"),
      expect.anything()
    );

    // rerender with max_level=3 should show all
    currentTimelineSearchParams = "task_id=task-a&max_level=3";
    view.rerender(
      <QueryClientProvider client={view.queryClient}>
        <TimelinePage />
      </QueryClientProvider>
    );
    await waitFor(() => {
      expect(screen.getAllByRole("button", { name: /节点 tree:/ })).toHaveLength(timeline.nodes.length);
    });
  });

  it("keeps tree_id deep link when controls change", async () => {
    const timeline = createEventTimeline();
    getTimelineMock.mockResolvedValue(timeline);
    const first = timeline.nodes[0];
    currentTimelineSearchParams = `task_id=task-a&tree_id=${encodeURIComponent(first!.tree_id)}`;
    const user = userEvent.setup();

    renderPage();

    await screen.findByText(`selected-${first!.tree_id}`);
    await user.click(screen.getByRole("button", { name: "切到重要" }));
    expect(navigateMock).toHaveBeenLastCalledWith(
      expect.stringContaining(`tree_id=${encodeURIComponent(first!.tree_id)}`),
      expect.anything()
    );
  });

  it("clears selection when detail panel is closed", async () => {
    const user = userEvent.setup();

    renderPage();

    await screen.findByText("selected-tree:1");
    await user.click(screen.getByRole("button", { name: "关闭详情" }));

    expect(navigateMock).toHaveBeenLastCalledWith(
      expect.not.stringContaining("tree_id="),
      expect.anything()
    );
  });

  it("shows error state and supports retry", async () => {
    getTimelineMock.mockRejectedValueOnce(new Error("boom")).mockResolvedValueOnce(createEventTimeline());

    renderPage();

    expect(await screen.findByText("加载失败")).toBeInTheDocument();
    const retryButtons = await screen.findAllByRole("button", { name: /重试/ });
    retryButtons[0]?.click();

    await waitFor(() => {
      expect(getTimelineMock).toHaveBeenCalledTimes(2);
    });
    expect(await screen.findByText(/selected-tree/)).toBeInTheDocument();
  });

  it("re-syncs without refetch when only display params change", async () => {
    const timeline = createEventTimeline();
    getTimelineMock.mockResolvedValue(timeline);
    const view = renderPage();

    expect(await screen.findByText("selected-tree:1")).toBeInTheDocument();
    expect(getTimelineMock).toHaveBeenCalledTimes(1);

    const second = timeline.nodes[1]?.tree_id ?? timeline.nodes[0]!.tree_id;
    currentTimelineSearchParams = `task_id=task-a&max_level=3&tree_id=${encodeURIComponent(second)}`;
    view.rerender(
      <QueryClientProvider client={view.queryClient}>
        <TimelinePage />
      </QueryClientProvider>
    );

    await waitFor(() => {
      expect(getTimelineMock).toHaveBeenCalledTimes(1);
    });
    expect(await screen.findByText(`selected-${second}`)).toBeInTheDocument();
  });
});
