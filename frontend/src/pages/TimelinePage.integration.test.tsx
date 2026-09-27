import { createElement } from "react";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Novel, TimelineEventNode } from "@/api/types";
import { TooltipProvider } from "@/components/ui/tooltip";
import { TimelinePage } from "@/pages/TimelinePage";
import { useNovelStore } from "@/store/novelStore";
import { createEventTimeline } from "@/mocks/data";

const getTimelineMock = vi.fn();
const getNovelMock = vi.fn();
const getAnalysisTasksMock = vi.fn();
const navigateMock = vi.fn();

let currentTimelineSearchParams = "task_id=task-integration&tree_id=tree%3A1";
let currentTimelineNovelId = "novel-1";

function motionElement(tagName: string) {
  const Component = (props: {
    children?: ReactNode;
    whileHover?: unknown;
    whileTap?: unknown;
    transition?: unknown;
    variants?: unknown;
    initial?: unknown;
    animate?: unknown;
    exit?: unknown;
    [key: string]: unknown;
  }) => {
    const sanitizedProps = { ...props };
    delete sanitizedProps.whileHover;
    delete sanitizedProps.whileTap;
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
  useParams: () => ({ novelId: currentTimelineNovelId }),
  useSearchParams: () => [new URLSearchParams(currentTimelineSearchParams)],
}));

vi.mock("framer-motion", () => ({
  AnimatePresence: ({ children }: { children?: ReactNode }) => <>{children}</>,
  motion: new Proxy(
    {},
    {
      get: (_target, key: string) => motionElement(key),
    }
  ),
}));

vi.mock("@/components/layout/PageContainer", () => ({
  PageContainer: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
}));
vi.mock("@/components/common/NovelHeader", () => ({
  NovelHeader: ({ title }: { title: string }) => <div>{title}</div>,
}));
vi.mock("@/components/common/MetricCard", () => ({
  MetricCard: ({ label, value }: { label: string; value: number }) => (
    <div>{label}:{value}</div>
  ),
}));

// mock timeline components like unit test to make integration deterministic
vi.mock("@/components/timeline", () => ({
  TimelineControls: ({ onMaxLevelChange }: { onMaxLevelChange: (l: 1 | 2 | 3) => void }) => (
    <div>
      <button type="button" onClick={() => onMaxLevelChange(1)}>
        重要
      </button>
      <button type="button" onClick={() => onMaxLevelChange(3)}>
        全部
      </button>
      <button type="button" onClick={() => navigateMock("/novels/novel-1/graph?task_id=task-integration&tree_id=tree%3A1")}>
        回到图谱入口
      </button>
    </div>
  ),
  PhaseBar: () => <div />,
  TimelineLegend: () => <div />,
  TensionOverlay: () => <div />,
  TimelineTrack: ({
    nodes,
    onNodeClick,
  }: {
    nodes: TimelineEventNode[];
    onNodeClick: (n: TimelineEventNode) => void;
  }) => (
    <div>
      {nodes.map((n) => (
        <button key={n.tree_id} type="button" onClick={() => onNodeClick(n)}>
          {n.tree_id}
        </button>
      ))}
    </div>
  ),
  TimelineEventInspector: ({ node, onSelectChapter }: { node: TimelineEventNode; onSelectChapter: (chapterId: number) => void }) => (
    <button type="button" onClick={() => onSelectChapter(node.anchor_chapter_id)}>定位事件章节 {node.tree_id}</button>
  ),
}));

vi.mock("@/api/results", () => ({
  getTimeline: (...args: unknown[]) => getTimelineMock(...args),
}));

vi.mock("@/api/novels", () => ({
  getNovel: (...args: unknown[]) => getNovelMock(...args),
}));

vi.mock("@/api/analysis", () => ({
  batchDeleteTasks: vi.fn(),
  cancelAnalysisTask: vi.fn(),
  getAnalysisTasks: (...args: unknown[]) => getAnalysisTasksMock(...args),
}));

function renderTimelinePage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <TimelinePage />
      </TooltipProvider>
    </QueryClientProvider>
  );
}

function createNovel(): Novel {
  return {
    novel_id: "novel-1",
    title: "Timeline Integration Novel",
    filename: "timeline.txt",
    author: "Tester",
    upload_time: "2026-04-23T00:00:00Z",
    file_size: 1,
  };
}

describe("TimelinePage integration (event forest)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    currentTimelineSearchParams = "task_id=task-integration&tree_id=tree%3A1";
    currentTimelineNovelId = "novel-1";
    useNovelStore.setState({ currentNovelId: null, currentTaskId: null, novelsCache: [] });
    getNovelMock.mockResolvedValue(createNovel());
    getAnalysisTasksMock.mockResolvedValue([]);
    getTimelineMock.mockResolvedValue(createEventTimeline());
  });

  it("keeps graph deep-link state through real timeline controls and detail actions", async () => {
    const user = userEvent.setup();
    const timeline = createEventTimeline();
    getTimelineMock.mockResolvedValue(timeline);
    renderTimelinePage();

    const first = timeline.nodes[0]!;
    expect(await screen.findByRole("button", { name: first.tree_id })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "重要" }));

    expect(navigateMock).toHaveBeenCalledWith(
      expect.stringContaining("max_level=1"),
      { replace: true }
    );
    // deep link tree_id should be preserved
    expect(navigateMock).toHaveBeenCalledWith(
      expect.stringContaining(encodeURIComponent(first.tree_id)),
      expect.anything()
    );

    // back to graph button should preserve tree_id
    await user.click(screen.getByRole("button", { name: /回到图谱入口/ }));
    expect(navigateMock).toHaveBeenCalledWith(expect.stringContaining("/novels/novel-1/graph"));
    expect(navigateMock).toHaveBeenCalledWith(expect.stringContaining(encodeURIComponent(first.tree_id)));
  });

  it("does not carry conflicting event_id back to graph when tree selection points elsewhere", async () => {
    const timeline = createEventTimeline();
    getTimelineMock.mockResolvedValue(timeline);
    const first = timeline.nodes[0]!;
    const second = timeline.nodes[1]!;
    currentTimelineSearchParams = `task_id=task-integration&tree_id=${encodeURIComponent(first.tree_id)}&event_id=${encodeURIComponent(second.root_event_id)}`;
    const user = userEvent.setup();

    renderTimelinePage();

    expect(await screen.findByRole("button", { name: first.tree_id })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /回到图谱入口/ }));

    expect(navigateMock).toHaveBeenCalledWith(expect.stringContaining(encodeURIComponent(first.tree_id)));
  });

  it("事件详情的章节入口定位到现有图谱路由", async () => {
    const user = userEvent.setup();
    const first = createEventTimeline().nodes[0]!;
    renderTimelinePage();

    await user.click(await screen.findByRole("tab", { name: "事件详情" }));
    await user.click(screen.getByRole("button", { name: `定位事件章节 ${first.tree_id}` }));
    expect(navigateMock).toHaveBeenCalledWith(
      `/novels/novel-1/graph?task_id=task-integration&selected_chapter=${first.anchor_chapter_id}`,
    );
  });

  it("事件轨道分页后仍能访问末页事件", async () => {
    const user = userEvent.setup();
    const timeline = createEventTimeline();
    const template = timeline.nodes[0]!;
    const nodes = Array.from({ length: 7 }, (_, index) => ({
      ...template,
      tree_id: `tree-page-${index + 1}`,
      root_event_id: `event-page-${index + 1}`,
      progress: (index + 1) / 8,
    }));
    currentTimelineSearchParams = "task_id=task-integration";
    getTimelineMock.mockResolvedValue({ ...timeline, nodes, derived_event_order: nodes.map((node) => node.root_event_id) });
    renderTimelinePage();

    expect(await screen.findByRole("button", { name: "tree-page-1" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "tree-page-6" })).not.toBeInTheDocument();
    const controls = screen.getByRole("navigation", { name: "事件轨道分页" });
    await user.click(within(controls).getByRole("button", { name: "下一页" }));
    expect(screen.getByRole("button", { name: "tree-page-6" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "tree-page-7" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "tree-page-1" })).not.toBeInTheDocument();
  });
});
