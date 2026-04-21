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
let currentGraphNovelId = "novel-1";

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
  useParams: () => ({ novelId: currentGraphNovelId }),
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
  GraphToolbar: ({
    relationTypes,
    selectedRelationTypes,
    onRelationTypeChange,
    searchQuery,
    onSearchChange,
  }: {
    relationTypes: string[];
    selectedRelationTypes: Set<string>;
    onRelationTypeChange: (types: Set<string>) => void;
    searchQuery: string;
    onSearchChange: (value: string) => void;
  }) => (
    <div data-testid="graph-toolbar">
      <span>{`search:${searchQuery || "none"}`}</span>
      <span>{`relations:${selectedRelationTypes.size}`}</span>
      <button type="button" onClick={() => onSearchChange("旧搜索")}>
        设置搜索
      </button>
      <button type="button" onClick={() => onRelationTypeChange(new Set(relationTypes.slice(0, 1)))}>
        设置关系过滤
      </button>
    </div>
  ),
}));

vi.mock("@/components/charts/GraphLegend", () => ({
  GraphLegend: passthroughComponent("graph-legend"),
}));

vi.mock("@/components/charts/NodeDetailPanel", () => ({
  NodeDetailPanel: ({ node }: { node?: GraphData["nodes"][number] | null }) => (
    <div data-testid="node-detail-panel">{node ? `selected-node:${node.name}` : "selected-node:none"}</div>
  ),
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

function createEmptyGraphData(): GraphData {
  return {
    nodes: [],
    edges: [],
    events: [],
    events_page: {
      limit: 200,
      returned_count: 0,
      total: 0,
      has_more: false,
      next_cursor: null,
    },
    summary: {
      node_count: 0,
      edge_count: 0,
      density: 0,
      core_characters: [],
      key_relations: [],
    },
    quality: {
      conflict_count: 0,
      low_confidence_count: 0,
      conflicts: [],
      low_confidence_samples: [],
    },
  };
}

function createContractBrokenGraphData(): GraphData {
  return {
    ...createGraphData("task-broken", {
      eventNames: [{ from: "task-broken Hero", to: "task-broken Ally", eventId: 101, chunkId: 50 }],
      total: 1,
      nextCursor: null,
    }),
    summary: undefined as unknown as GraphData["summary"],
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

function renderPage(queryClient = createQueryClient()) {
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
    currentGraphNovelId = "novel-1";
    useNovelStore.setState({
      currentNovelId: null,
      currentTaskId: null,
      novelsCache: [],
    });
    getNovelMock.mockResolvedValue(createNovel());
    getCharactersMock.mockResolvedValue([]);
  });

  it("shows the no-task empty state when no task is selected", async () => {
    currentGraphSearchParams = "";
    useNovelStore.setState({
      currentNovelId: null,
      currentTaskId: null,
      novelsCache: [],
    });

    renderPage();

    expect(await screen.findByText("请先选择分析任务")).toBeInTheDocument();
    expect(getGraphMock).not.toHaveBeenCalled();
  });

  it("keeps the URL deep-link task authoritative when the store still holds an older task", async () => {
    currentGraphSearchParams = "task_id=task-a&selected_chunk=48&relation_event_id=9999";
    useNovelStore.setState({
      currentNovelId: "novel-1",
      currentTaskId: "task-b",
      novelsCache: [],
    });
    getGraphMock.mockResolvedValue(
      createGraphData("task-a", {
        eventNames: [{ from: "task-a Hero", to: "task-a Ally", eventId: 101, chunkId: 48 }],
        total: 1,
        nextCursor: null,
      })
    );

    renderPage();

    await screen.findByText("task-a Hero");
    expect(getGraphMock).toHaveBeenCalledWith("novel-1", "task-a");
    expect(navigateMock).not.toHaveBeenCalledWith("/novels/novel-1/graph?task_id=task-b", { replace: true });
  });

  it("reflects an in-page task switch back into the graph url", async () => {
    currentGraphSearchParams = "task_id=task-a&selected_chunk=48&relation_event_id=9999";
    useNovelStore.setState({
      currentNovelId: "novel-1",
      currentTaskId: "task-a",
      novelsCache: [],
    });
    getGraphMock.mockImplementation(async (_novelId: string, taskId: string) =>
      createGraphData(taskId, {
        eventNames: [{ from: `${taskId} Hero`, to: `${taskId} Ally`, eventId: taskId === "task-a" ? 101 : 301, chunkId: 48 }],
        total: 1,
        nextCursor: null,
      })
    );

    renderPage();

    await screen.findByText("task-a Hero");
    useNovelStore.setState({
      currentNovelId: "novel-1",
      currentTaskId: "task-b",
      novelsCache: [],
    });

    await waitFor(() => {
      expect(navigateMock).toHaveBeenCalledWith("/novels/novel-1/graph?task_id=task-b", { replace: true });
    });
  });

  it("shows the missing-novel state when the route param is absent", async () => {
    currentGraphNovelId = undefined as unknown as string;
    useNovelStore.setState({
      currentNovelId: "novel-1",
      currentTaskId: "task-a",
      novelsCache: [],
    });

    renderPage();

    expect(await screen.findByText("小说不存在")).toBeInTheDocument();
    expect(getGraphMock).not.toHaveBeenCalled();
    expect(getNovelMock).not.toHaveBeenCalled();
    expect(navigateMock).not.toHaveBeenCalled();
  });

  it("shows the graph error state and supports retry", async () => {
    const taskAGraph = createGraphData("task-a", {
      eventNames: [{ from: "task-a Hero", to: "task-a Ally", eventId: 101, chunkId: 50 }],
      total: 1,
      nextCursor: null,
    });
    getGraphMock.mockRejectedValueOnce(new Error("boom")).mockResolvedValueOnce(taskAGraph);

    const user = userEvent.setup();
    renderPage();

    expect(await screen.findByText("图谱数据加载失败")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /重试/ }));

    expect(await screen.findByText("task-a Hero")).toBeInTheDocument();
    expect(getGraphMock).toHaveBeenCalledTimes(2);
  });

  it("shows the empty graph state when the task has no graph nodes", async () => {
    getGraphMock.mockResolvedValue(createEmptyGraphData());

    renderPage();

    await screen.findByText(/该任务暂时没有可展示的关系图谱/);
  });

  it("shows the graph contract issue state when required page fields are missing", async () => {
    const consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    getGraphMock.mockResolvedValue(createContractBrokenGraphData());

    renderPage();

    await screen.findByText(/图谱数据暂不完整/);
    expect(consoleErrorSpy).toHaveBeenCalled();
    consoleErrorSpy.mockRestore();
  });

  it("keeps cached graph events visible on first mount instead of clearing the preloaded window", async () => {
    useNovelStore.setState({
      currentNovelId: "novel-1",
      currentTaskId: "task-a",
      novelsCache: [],
    });
    const cachedGraph = createGraphData("task-a", {
      eventNames: [{ from: "task-a Hero", to: "task-a Ally", eventId: 101, chunkId: 50 }],
      total: 2,
      nextCursor: "cursor-a-1",
    });
    const queryClient = createQueryClient();
    queryClient.setQueryData(["graph", "novel-1", "task-a"], cachedGraph);

    renderPage(queryClient);

    expect((await screen.findAllByText(/第 50 段 · task-a Hero → task-a Ally/)).length).toBeGreaterThan(0);
    expect(screen.getByText("1 / 2")).toBeInTheDocument();
    expect(getGraphMock).not.toHaveBeenCalled();
  });

  it("keeps cached graph events visible when switching into another task that is already cached", async () => {
    useNovelStore.setState({
      currentNovelId: "novel-1",
      currentTaskId: "task-a",
      novelsCache: [],
    });
    const taskAGraph = createGraphData("task-a", {
      eventNames: [{ from: "task-a Hero", to: "task-a Ally", eventId: 101, chunkId: 50 }],
      total: 1,
      nextCursor: null,
    });
    const taskBGraph = createGraphData("task-b", {
      eventNames: [{ from: "task-b Hero", to: "task-b Ally", eventId: 401, chunkId: 42 }],
      total: 2,
      nextCursor: "cursor-b-1",
    });
    const queryClient = createQueryClient();
    queryClient.setQueryData(["graph", "novel-1", "task-a"], taskAGraph);
    queryClient.setQueryData(["graph", "novel-1", "task-b"], taskBGraph);

    const view = renderPage(queryClient);

    await screen.findByText("task-a Hero");

    currentGraphSearchParams = "task_id=task-b";
    view.rerender(
      <QueryClientProvider client={view.queryClient}>
        <GraphPage />
      </QueryClientProvider>,
    );

    await screen.findByText("task-b Hero");
    expect(screen.getByText("1 / 2")).toBeInTheDocument();
    expect(screen.getByText(/task-b Hero -> task-b Ally/)).toBeInTheDocument();
    expect(screen.queryByText("暂无关系变化记录。")).not.toBeInTheDocument();
    expect(getGraphMock).not.toHaveBeenCalled();
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

  it("shows load-more errors and clears them after a successful retry", async () => {
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

    getGraphMock.mockResolvedValue(taskAGraph);
    getGraphEventsMock.mockRejectedValueOnce(new Error("分页失败")).mockResolvedValueOnce(taskASecondPage);

    const user = userEvent.setup();
    renderPage();

    await screen.findByText("task-a Hero");
    await user.click(await screen.findByRole("button", { name: "加载更多" }));
    expect(await screen.findByText("分页失败")).toBeInTheDocument();

    await user.click(await screen.findByRole("button", { name: "加载更多" }));
    await screen.findByText(/task-a Extra → task-a Ally/);
    expect(screen.queryByText("分页失败")).not.toBeInTheDocument();
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

  it("preserves a chunk-only deep-link when jumping back to timeline without a matched relation event", async () => {
    currentGraphSearchParams = "task_id=task-a&selected_chunk=48";
    const taskAGraph = createGraphData("task-a", {
      eventNames: [{ from: "task-a Hero", to: "task-a Ally", eventId: 101, chunkId: 50 }],
      total: 1,
      nextCursor: null,
    });

    getGraphMock.mockResolvedValue(taskAGraph);

    const user = userEvent.setup();
    renderPage();

    await screen.findByText("task-a Hero");
    await user.click(screen.getByRole("button", { name: "去时间轴联动查看" }));

    expect(navigateMock).toHaveBeenCalledWith(
      "/novels/novel-1/timeline?task_id=task-a&max_level=3&show_tension=true&selected_chunk=48"
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

    expect(await screen.findByText("变化类型")).toBeInTheDocument();
    expect(screen.getByText(/task-a Older -> task-a Ally/)).toBeInTheDocument();
  });

  it("uses the resolved fallback event when jumping back to timeline after a graph deep-link miss", async () => {
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

    await screen.findByText(/task-a Older -> task-a Ally/);
    await user.click(screen.getByRole("button", { name: "去时间轴联动查看" }));

    expect(navigateMock).toHaveBeenCalledWith(
      "/novels/novel-1/timeline?task_id=task-a&max_level=3&show_tension=true&selected_chunk=48&relation_event_id=102"
    );
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

    renderPage();

    await screen.findByText(/未在当前事件窗口定位到指定关系事件/);
    const targetEventButton = screen.getByText(/第 50 段 · task-a Hero → task-a Ally/).closest("button");
    expect(targetEventButton).not.toBeNull();
    navigateMock.mockClear();
    fireEvent.click(targetEventButton!);

    await waitFor(() => {
      expect(
        screen.queryByText("未在当前事件窗口定位到指定关系事件，已回退到同一时间节点的关系变化。")
      ).not.toBeInTheDocument();
    });
    expect(screen.getByText(/task-a Hero -> task-a Ally/)).toBeInTheDocument();
    expect(navigateMock).toHaveBeenCalledWith(
      "/novels/novel-1/graph?task_id=task-a&selected_chunk=50&relation_event_id=101",
      { replace: true }
    );
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
      expect(screen.queryByText("变化类型")).not.toBeInTheDocument();
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

  it("clears stale node selection, event detail, load-more errors, and deep-link hints after switching tasks", async () => {
    currentGraphSearchParams = "task_id=task-a&selected_chunk=48&relation_event_id=9999";
    const taskAGraph = createGraphData("task-a", {
      eventNames: [
        { from: "task-a Hero", to: "task-a Ally", eventId: 101, chunkId: 50 },
        { from: "task-a Older", to: "task-a Ally", eventId: 102, chunkId: 48 },
      ],
      total: 3,
      nextCursor: "cursor-a-1",
    });
    const taskBGraph = createGraphData("task-b", {
      eventNames: [{ from: "task-b Hero", to: "task-b Ally", eventId: 301, chunkId: 40 }],
      total: 1,
      nextCursor: null,
    });

    getGraphMock.mockImplementation(async (_novelId: string, taskId: string) => {
      if (taskId === "task-a") return taskAGraph;
      if (taskId === "task-b") return taskBGraph;
      throw new Error(`unexpected task id: ${taskId}`);
    });
    getGraphEventsMock.mockRejectedValue(new Error("旧任务分页失败"));

    const user = userEvent.setup();
    const view = renderPage();

    await screen.findByText(/未在当前事件窗口定位到指定关系事件/);
    await user.click(screen.getByRole("button", { name: "选择第一个节点" }));
    expect(screen.getByText(/task-a Older -> task-a Ally/)).toBeInTheDocument();

    await user.click(await screen.findByRole("button", { name: "加载更多" }));
    expect(await screen.findByText("旧任务分页失败")).toBeInTheDocument();

    currentGraphSearchParams = "task_id=task-b";
    view.rerender(
      <QueryClientProvider client={view.queryClient}>
        <GraphPage />
      </QueryClientProvider>,
    );

    await screen.findByText("task-b Hero");
    expect(screen.queryByText("旧任务分页失败")).not.toBeInTheDocument();
    expect(screen.queryByText(/未在当前事件窗口定位到指定关系事件/)).not.toBeInTheDocument();
    expect(screen.getByText("selected-node:none")).toBeInTheDocument();
    expect(screen.queryByText(/task-a Older -> task-a Ally/)).not.toBeInTheDocument();
    expect(screen.getByText(/task-b Hero -> task-b Ally/)).toBeInTheDocument();
  });

  it("clears toolbar search and relation filters after switching tasks", async () => {
    const taskAGraph = createGraphData("task-a", {
      eventNames: [{ from: "task-a Hero", to: "task-a Ally", eventId: 101, chunkId: 50 }],
      total: 1,
      nextCursor: null,
    });
    const taskBGraph = createGraphData("task-b", {
      eventNames: [{ from: "task-b Hero", to: "task-b Ally", eventId: 301, chunkId: 40 }],
      total: 1,
      nextCursor: null,
    });

    getGraphMock.mockImplementation(async (_novelId: string, taskId: string) => {
      if (taskId === "task-a") return taskAGraph;
      if (taskId === "task-b") return taskBGraph;
      throw new Error(`unexpected task id: ${taskId}`);
    });

    const user = userEvent.setup();
    const view = renderPage();

    await screen.findByText("task-a Hero");
    await user.click(screen.getByRole("button", { name: "设置搜索" }));
    await user.click(screen.getByRole("button", { name: "设置关系过滤" }));
    expect(screen.getByText("search:旧搜索")).toBeInTheDocument();
    expect(screen.getByText("relations:1")).toBeInTheDocument();

    currentGraphSearchParams = "task_id=task-b";
    view.rerender(
      <QueryClientProvider client={view.queryClient}>
        <GraphPage />
      </QueryClientProvider>,
    );

    await screen.findByText("task-b Hero");
    expect(screen.getByText("search:none")).toBeInTheDocument();
    expect(screen.getByText("relations:0")).toBeInTheDocument();
  });

  it("keeps node selection and event detail when the same task snapshot refreshes", async () => {
    const initialGraph = createGraphData("task-a", {
      eventNames: [
        { from: "task-a Hero", to: "task-a Ally", eventId: 101, chunkId: 50 },
        { from: "task-a Older", to: "task-a Ally", eventId: 102, chunkId: 48 },
      ],
      total: 3,
      nextCursor: "cursor-a-1",
    });
    const refreshedGraph = createGraphData("task-a", {
      eventNames: [
        { from: "task-a Hero", to: "task-a Ally", eventId: 101, chunkId: 50 },
        { from: "task-a Older", to: "task-a Ally", eventId: 102, chunkId: 48 },
      ],
      total: 4,
      nextCursor: "cursor-a-2",
    });

    getGraphMock.mockResolvedValue(initialGraph);

    const user = userEvent.setup();
    const view = renderPage();

    await screen.findByText("task-a Hero");
    await user.click(screen.getByRole("button", { name: "选择第一个节点" }));
    const targetEventButton = screen.getByText(/第 48 段 · task-a Older → task-a Ally/).closest("button");
    expect(targetEventButton).not.toBeNull();
    fireEvent.click(targetEventButton!);
    expect(screen.getByText("selected-node:task-a Hero")).toBeInTheDocument();
    expect(screen.getByText(/task-a Older -> task-a Ally/)).toBeInTheDocument();

    view.queryClient.setQueryData(["graph", "novel-1", "task-a"], refreshedGraph);

    await waitFor(() => {
      expect(screen.getByText("selected-node:task-a Hero")).toBeInTheDocument();
      expect(screen.getByText(/task-a Older -> task-a Ally/)).toBeInTheDocument();
      expect(screen.getByText("2 / 4")).toBeInTheDocument();
    });
  });
});
