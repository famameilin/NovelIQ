import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { EventTimelineResponse, TimelineEventNode } from "@/api/types";
import { createEventTimeline } from "@/mocks/data";
import { TimelinePage } from "@/pages/TimelinePage";
import { useNovelStore } from "@/store/novelStore";

const getTimelineMock = vi.fn();
const getNovelMock = vi.fn();

vi.mock("@/api/results", () => ({ getTimeline: (...args: unknown[]) => getTimelineMock(...args) }));
vi.mock("@/api/novels", () => ({ getNovel: (...args: unknown[]) => getNovelMock(...args) }));
vi.mock("@/components/layout/AnalysisWorkspace", () => ({
  AnalysisWorkspace: ({ children }: { children: ReactNode }) => <main>{children}</main>,
}));
vi.mock("@/components/timeline", () => ({
  TimelineControls: ({ onMaxLevelChange }: { onMaxLevelChange: (level: 1 | 2 | 3) => void }) => (
    <div>
      <button onClick={() => onMaxLevelChange(1)}>重要</button>
      <button onClick={() => onMaxLevelChange(3)}>全部</button>
    </div>
  ),
  TimelineLegend: () => <div>图例内容</div>,
  TimelineTrack: ({ nodes, onNodeClick }: {
    nodes: TimelineEventNode[];
    onNodeClick: (node: TimelineEventNode, card: HTMLElement) => void;
  }) => <div>{nodes.map((node) => (
    <button key={node.tree_id} onClick={(event) => onNodeClick(node, event.currentTarget)}>
      {node.tree_id}
    </button>
  ))}</div>,
  TimelineEventInspector: ({ node, onClose }: { node: TimelineEventNode; onClose: () => void }) => (
    <div><p>已选中 {node.tree_id}</p><button onClick={onClose}>关闭详情</button></div>
  ),
}));

function fixture(): EventTimelineResponse {
  const base = createEventTimeline();
  const template = base.nodes[0]!;
  const nodes = Array.from({ length: 7 }, (_, index) => ({
    ...template,
    tree_id: `tree-${index + 1}`,
    root_event_id: `event-${index + 1}`,
    level: index < 2 ? 1 : 3,
    progress: (index + 1) / 8,
    main_chain: [`event-${index + 1}`],
  })) as TimelineEventNode[];
  return {
    ...base,
    nodes,
    derived_event_order: nodes.map((node) => node.root_event_id),
    meta: { ...base.meta, total_chapters: 8 },
    total_chapters: 8,
  };
}

function renderPage(url = "/novels/novel-1/timeline?task_id=task-a") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter([
    { path: "/novels/:novelId/timeline", element: <TimelinePage /> },
    { path: "/novels/:novelId/graph", element: <p>图谱</p> },
  ], { initialEntries: [url] });
  render(<QueryClientProvider client={client}><RouterProvider router={router} /></QueryClientProvider>);
  return router;
}

beforeEach(() => {
  getTimelineMock.mockReset().mockResolvedValue(fixture());
  getNovelMock.mockReset().mockResolvedValue({ novel_id: "novel-1", title: "测试小说" });
  useNovelStore.setState({ currentNovelId: "novel-1", currentTaskId: "task-a", novelsCache: [] });
});

describe("连续事件轨道", () => {
  it("一次展示全部节点，筛选仅改变可见事件，不提供轨道分页", async () => {
    const router = renderPage();
    const track = await screen.findByRole("region", { name: "事件轨道" });
    expect(within(track).getAllByRole("button")).toHaveLength(7);
    expect(within(track).getAllByRole("button").map((button) => button.textContent)).toEqual(
      Array.from({ length: 7 }, (_, index) => `tree-${index + 1}`),
    );
    expect(screen.queryByRole("navigation", { name: "事件轨道分页" })).not.toBeInTheDocument();

    await userEvent.setup().click(screen.getByRole("button", { name: "重要" }));
    await waitFor(() => expect(router.state.location.search).toContain("max_level=1"));
    expect(within(track).getAllByRole("button")).toHaveLength(2);
    expect(getTimelineMock).toHaveBeenCalledTimes(1);
  });

  it("点击末尾卡片打开悬浮详情，关闭后保留连续轨道", async () => {
    const router = renderPage();
    const track = await screen.findByRole("region", { name: "事件轨道" });
    await userEvent.setup().click(within(track).getByRole("button", { name: "tree-7" }));

    expect(await screen.findByRole("dialog", { name: "事件详情悬浮框" })).toHaveTextContent("已选中 tree-7");
    expect(router.state.location.search).toContain("tree_id=tree-7");
    expect(router.state.location.search).toContain("event_id=event-7");
    await userEvent.setup().click(screen.getByRole("button", { name: "关闭详情" }));
    expect(screen.queryByRole("dialog", { name: "事件详情悬浮框" })).not.toBeInTheDocument();
    expect(within(track).getAllByRole("button")).toHaveLength(7);
    expect(router.state.location.search).not.toContain("tree_id=");
  });

  it("旧任务状态不能覆盖深链任务，tree_id 和 event_id 仍在时间轴打开详情", async () => {
    useNovelStore.setState({ currentNovelId: "novel-1", currentTaskId: "task-old" });
    const router = renderPage("/novels/novel-1/timeline?task_id=task-a&tree_id=tree-4&event_id=event-4");
    expect(await screen.findByRole("dialog", { name: "事件详情悬浮框" })).toHaveTextContent("已选中 tree-4");
    expect(router.state.location.pathname).toBe("/novels/novel-1/timeline");
    expect(getTimelineMock).toHaveBeenCalledWith("novel-1", "task-a", { includeCurve: true });

    await userEvent.setup().click(screen.getByRole("button", { name: "重要" }));
    expect(router.state.location.search).toContain("tree_id=tree-4");
    expect(router.state.location.search).toContain("max_level=1");
  });

  it("缺失任务时不请求时间轴", () => {
    useNovelStore.setState({ currentNovelId: "novel-1", currentTaskId: null });
    renderPage("/novels/novel-1/timeline");
    expect(screen.getByText("请先选择分析任务")).toBeInTheDocument();
    expect(getTimelineMock).not.toHaveBeenCalled();
  });

  it("无节点结果显示空状态", async () => {
    const empty = fixture();
    empty.nodes = [];
    getTimelineMock.mockResolvedValueOnce(empty);
    renderPage();
    expect(await screen.findByText("暂无时间轴节点")).toBeInTheDocument();
  });

  it("失效树深链保留轨道并提示未找到事件", async () => {
    renderPage("/novels/novel-1/timeline?task_id=task-a&tree_id=missing");
    expect(await screen.findByRole("region", { name: "事件轨道" })).toBeInTheDocument();
    expect(screen.getByText("未找到链接指向的事件，已保留当前时间轴内容")).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "事件详情悬浮框" })).not.toBeInTheDocument();
  });

  it("仅提供旁支 event_id 的深链也能定位所属树", async () => {
    const data = fixture();
    data.nodes[2]!.secondary_groups = [{ target_event_id: "event-3", branch: ["event-3-side"] }];
    getTimelineMock.mockResolvedValueOnce(data);
    renderPage("/novels/novel-1/timeline?task_id=task-a&event_id=event-3-side");
    expect(await screen.findByRole("dialog", { name: "事件详情悬浮框" })).toHaveTextContent("已选中 tree-3");
  });

  it("请求失败后可重试加载轨道", async () => {
    getTimelineMock.mockReset().mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce(fixture());
    renderPage();
    expect(await screen.findByText("时间轴加载失败")).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("button", { name: "重试" }));
    expect(await screen.findByRole("region", { name: "事件轨道" })).toBeInTheDocument();
    expect(getTimelineMock).toHaveBeenCalledTimes(2);
  });
});
