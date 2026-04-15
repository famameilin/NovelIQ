import { createElement } from "react";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { GraphData, GraphEventsPageResponse, Novel } from "@/api/types";
import { useNovelStore } from "@/store/novelStore";
import { GraphPage } from "@/pages/GraphPage";

const getGraphMock = vi.fn();
const getCharactersMock = vi.fn();
const getGraphEventsMock = vi.fn();
const getNovelMock = vi.fn();
const navigateMock = vi.fn();

let currentGraphSearchParams = "task_id=task-a";

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
    return createElement(tagName, sanitizedProps, props.children);
  };
  Component.displayName = `motion-${tagName}`;
  return Component;
}

vi.mock("react-router-dom", () => ({
  useNavigate: () => navigateMock,
  useParams: () => ({ novelId: "novel-1" }),
  useSearchParams: () => [new URLSearchParams(currentGraphSearchParams)],
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
  MetricCard: ({ label, value }: { label: string; value: string | number }) => (
    <div>
      <span>{label}</span>
      <span>{value}</span>
    </div>
  ),
}));

vi.mock("@/components/charts/ForceGraph", () => ({
  ForceGraph: ({ data, onNodeClick }: { data?: GraphData; onNodeClick?: (node: GraphData["nodes"][number]) => void }) => (
    <div data-testid="force-graph">
      <button type="button" onClick={() => data?.nodes?.[0] && onNodeClick?.(data.nodes[0])}>
        选择第一个节点
      </button>
    </div>
  ),
}));

vi.mock("@/components/charts/GraphToolbar", () => ({
  GraphToolbar: passthroughComponent("graph-toolbar"),
}));

vi.mock("@/components/charts/GraphLegend", () => ({
  GraphLegend: passthroughComponent("graph-legend"),
}));

vi.mock("@/components/charts/NodeDetailPanel", () => ({
  NodeDetailPanel: passthroughComponent("node-detail-panel"),
}));

vi.mock("@/api/results", () => ({
  getGraph: (...args: unknown[]) => getGraphMock(...args),
  getCharacters: (...args: unknown[]) => getCharactersMock(...args),
  getGraphEvents: (...args: unknown[]) => getGraphEventsMock(...args),
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

function createGraphData(
  taskLabel: string,
  options: {
    eventNames: Array<{ from: string; to: string; eventId: number; chunkId: number }>;
    total: number;
    nextCursor: string | null;
  },
): GraphData {
  const { eventNames, total, nextCursor } = options;
  const heroId = `${taskLabel}-hero`;
  const allyId = `${taskLabel}-ally`;
  return {
    nodes: [
      {
        entity_id: heroId,
        name: `${taskLabel} Hero`,
        entity_type: "character",
        first_seen_chunk: 1,
        last_seen_chunk: 100,
        role: "protagonist",
        status: "active",
      },
      {
        entity_id: allyId,
        name: `${taskLabel} Ally`,
        entity_type: "character",
        first_seen_chunk: 1,
        last_seen_chunk: 100,
        role: "supporting",
        status: "active",
      },
    ],
    edges: [
      {
        source: heroId,
        target: allyId,
        relation_type: "盟友",
        weight: 1,
        from_name: `${taskLabel} Hero`,
        to_name: `${taskLabel} Ally`,
        change_count: eventNames.length,
        tension_index: 0,
        is_active: true,
      },
    ],
    events: eventNames.map((event) => ({
      relation_event_id: event.eventId,
      chunk_id: event.chunkId,
      from_entity_id: 1,
      to_entity_id: 2,
      from_name: event.from,
      to_name: event.to,
      relation_type: "盟友",
      change_type: "新建",
      evidence: `${event.from} -> ${event.to}`,
      confidence: 0.9,
      source_relation_row_id: event.eventId,
      directionality: "bidirectional",
    })),
    events_page: {
      limit: 1,
      returned_count: eventNames.length,
      total,
      has_more: nextCursor != null,
      next_cursor: nextCursor,
    },
    summary: {
      node_count: 2,
      edge_count: 1,
      density: 0.5,
      core_characters: [`${taskLabel} Hero`, `${taskLabel} Ally`],
      key_relations: [
        {
          from: `${taskLabel} Hero`,
          to: `${taskLabel} Ally`,
          type: "盟友",
          support_count: 1,
        },
      ],
    },
    quality: {
      conflict_count: 0,
      low_confidence_count: 0,
      conflicts: [],
      low_confidence_samples: [],
    },
  };
}

function createNovel(): Novel {
  return {
    novel_id: "novel-1",
    title: "Graph Review Novel",
    filename: "graph.txt",
    author: "Tester",
    upload_time: "2026-04-15T00:00:00Z",
    file_size: 1,
  };
}

function createDeferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

function renderPage() {
  const queryClient = createQueryClient();
  const view = render(
    <QueryClientProvider client={queryClient}>
      <GraphPage />
    </QueryClientProvider>,
  );
  return { queryClient, ...view };
}

describe("GraphPage pagination", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    currentGraphSearchParams = "task_id=task-a";
    useNovelStore.setState({
      currentNovelId: null,
      currentTaskId: null,
      novelsCache: [],
    });
    getNovelMock.mockResolvedValue(createNovel());
    getCharactersMock.mockResolvedValue([]);
  });

  it("merges load-more history into the current task window", async () => {
    const taskAGraph = createGraphData("task-a", {
      eventNames: [{ from: "task-a Hero", to: "task-a Ally", eventId: 101, chunkId: 50 }],
      total: 2,
      nextCursor: "cursor-a-1",
    });
    const taskASecondPage: GraphEventsPageResponse = {
      events: [
        {
          relation_event_id: 102,
          chunk_id: 48,
          from_entity_id: 1,
          to_entity_id: 2,
          from_name: "task-a Extra",
          to_name: "task-a Ally",
          relation_type: "盟友",
          change_type: "强化",
          evidence: "task-a Extra -> task-a Ally",
          confidence: 0.88,
          source_relation_row_id: 102,
          directionality: "bidirectional",
        },
      ],
      page_info: {
        limit: 1,
        returned_count: 1,
        total: 2,
        has_more: false,
        next_cursor: null,
      },
    };

    getGraphMock.mockImplementation(async (_novelId: string, taskId: string) => {
      expect(taskId).toBe("task-a");
      return taskAGraph;
    });
    getGraphEventsMock.mockResolvedValue(taskASecondPage);

    const user = userEvent.setup();
    renderPage();

    await screen.findByText("task-a Hero");
    await user.click(await screen.findByRole("button", { name: "加载更多" }));

    await screen.findByText(/task-a Extra → task-a Ally/);
    expect(screen.queryByRole("button", { name: "加载更多" })).not.toBeInTheDocument();
  });

  it("navigates to timeline with the selected relation event", async () => {
    const taskAGraph = createGraphData("task-a", {
      eventNames: [{ from: "task-a Hero", to: "task-a Ally", eventId: 101, chunkId: 50 }],
      total: 1,
      nextCursor: null,
    });

    getGraphMock.mockResolvedValue(taskAGraph);

    const user = userEvent.setup();
    renderPage();

    await screen.findByText("task-a Hero");
    await user.click(await screen.findByRole("button", { name: "去时间轴联动查看" }));

    expect(navigateMock).toHaveBeenCalledWith(
      "/novels/novel-1/timeline?task_id=task-a&max_level=3&show_tension=true&selected_chunk=50&relation_event_id=101"
    );
  });

  it("opens timeline lifecycle entry points for the selected character node", async () => {
    const taskAGraph = createGraphData("task-a", {
      eventNames: [{ from: "task-a Hero", to: "task-a Ally", eventId: 101, chunkId: 50 }],
      total: 1,
      nextCursor: null,
    });

    getGraphMock.mockResolvedValue(taskAGraph);

    const user = userEvent.setup();
    renderPage();

    await screen.findByText("task-a Hero");
    await user.click(await screen.findByRole("button", { name: "选择第一个节点" }));
    await user.click(await screen.findByRole("button", { name: "查看首次登场" }));

    expect(navigateMock).toHaveBeenCalledWith(
      "/novels/novel-1/timeline?task_id=task-a&max_level=3&show_tension=true&selected_chunk=1"
    );
  });

  it("falls back to selected_chunk when the deep-linked relation event is not in the current page window", async () => {
    currentGraphSearchParams = "task_id=task-a&selected_chunk=48&relation_event_id=9999";
    const taskAGraph = createGraphData("task-a", {
      eventNames: [
        { from: "task-a Hero", to: "task-a Ally", eventId: 101, chunkId: 50 },
        { from: "task-a Older", to: "task-a Ally", eventId: 102, chunkId: 48 },
      ],
      total: 2,
      nextCursor: null,
    });

    getGraphMock.mockResolvedValue(taskAGraph);

    renderPage();

    expect(await screen.findByText("事件 ID")).toBeInTheDocument();
    expect(screen.getByText("102")).toBeInTheDocument();
  });

  it("clears the deep-link fallback hint after the user manually selects an event", async () => {
    currentGraphSearchParams = "task_id=task-a&selected_chunk=48&relation_event_id=9999";
    const taskAGraph = createGraphData("task-a", {
      eventNames: [
        { from: "task-a Hero", to: "task-a Ally", eventId: 101, chunkId: 50 },
        { from: "task-a Older", to: "task-a Ally", eventId: 102, chunkId: 48 },
      ],
      total: 2,
      nextCursor: null,
    });

    getGraphMock.mockResolvedValue(taskAGraph);

    const user = userEvent.setup();
    renderPage();

    expect(await screen.findByText("未在当前事件窗口定位到指定关系事件，已回退到同一时间节点的关系变化。")).toBeInTheDocument();
    const targetEventButton = screen.getByText(/第 50 段 · task-a Hero → task-a Ally/).closest("button");
    expect(targetEventButton).not.toBeNull();
    fireEvent.click(targetEventButton!);

    await waitFor(() => {
      expect(
        screen.queryByText("未在当前事件窗口定位到指定关系事件，已回退到同一时间节点的关系变化。")
      ).not.toBeInTheDocument();
    });
    expect(screen.getByText("101")).toBeInTheDocument();
  });

  it("clears the graph event selection instead of highlighting the wrong event when no deep-link match exists", async () => {
    currentGraphSearchParams = "task_id=task-a&selected_chunk=999&relation_event_id=9999";
    const taskAGraph = createGraphData("task-a", {
      eventNames: [{ from: "task-a Hero", to: "task-a Ally", eventId: 101, chunkId: 50 }],
      total: 1,
      nextCursor: null,
    });

    getGraphMock.mockResolvedValue(taskAGraph);

    renderPage();

    await screen.findByText("task-a Hero");
    await waitFor(() => {
      expect(screen.queryByText("事件 ID")).not.toBeInTheDocument();
    });
    expect(screen.getByText(/这里会显示详细上下文/)).toBeInTheDocument();
  });

  it("ignores stale load-more responses after switching tasks", async () => {
    const taskAGraph = createGraphData("task-a", {
      eventNames: [{ from: "task-a Hero", to: "task-a Ally", eventId: 201, chunkId: 60 }],
      total: 3,
      nextCursor: "cursor-a-1",
    });
    const taskBGraph = createGraphData("task-b", {
      eventNames: [{ from: "task-b Hero", to: "task-b Ally", eventId: 301, chunkId: 40 }],
      total: 2,
      nextCursor: "cursor-b-1",
    });
    const staleTaskAPage = createDeferred<GraphEventsPageResponse>();

    getGraphMock.mockImplementation(async (_novelId: string, taskId: string) => {
      if (taskId === "task-a") {
        return taskAGraph;
      }
      if (taskId === "task-b") {
        return taskBGraph;
      }
      throw new Error(`unexpected task id: ${taskId}`);
    });
    getGraphEventsMock.mockImplementation(async (_novelId: string, taskId: string) => {
      if (taskId !== "task-a") {
        throw new Error(`unexpected task id for load more: ${taskId}`);
      }
      return staleTaskAPage.promise;
    });

    const user = userEvent.setup();
    const view = renderPage();

    await screen.findByText("task-a Hero");
    await user.click(await screen.findByRole("button", { name: "加载更多" }));

    currentGraphSearchParams = "task_id=task-b";
    view.rerender(
      <QueryClientProvider client={view.queryClient}>
        <GraphPage />
      </QueryClientProvider>,
    );

    await screen.findByText("task-b Hero");
    staleTaskAPage.resolve({
      events: [
        {
          relation_event_id: 202,
          chunk_id: 58,
          from_entity_id: 1,
          to_entity_id: 2,
          from_name: "task-a Extra",
          to_name: "task-a Ally",
          relation_type: "盟友",
          change_type: "强化",
          evidence: "stale task-a page",
          confidence: 0.88,
          source_relation_row_id: 202,
          directionality: "bidirectional",
        },
      ],
      page_info: {
        limit: 1,
        returned_count: 1,
        total: 3,
        has_more: false,
        next_cursor: null,
      },
    });

    await waitFor(() => {
      expect(screen.queryByText(/task-a Extra → task-a Ally/)).not.toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: "加载更多" })).toBeEnabled();
    expect(screen.getByText("1 / 2")).toBeInTheDocument();
  });
});
