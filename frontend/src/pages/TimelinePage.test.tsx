import { createElement } from "react";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Novel, TimelineResponse } from "@/api/types";
import { TimelinePage } from "@/pages/TimelinePage";
import { useNovelStore } from "@/store/novelStore";

const getTimelineMock = vi.fn();
const getNovelMock = vi.fn();
const navigateMock = vi.fn();

let currentTimelineSearchParams = "task_id=task-a&selected_chunk=12&relation_event_id=9002";

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

vi.mock("@/components/timeline", () => ({
  TimelineControls: passthroughComponent("timeline-controls"),
  PhaseBar: passthroughComponent("phase-bar"),
  TensionOverlay: passthroughComponent("tension-overlay"),
  TimelineTrack: ({ nodes, onNodeClick }: { nodes: TimelineResponse["nodes"]; onNodeClick: (node: TimelineResponse["nodes"][number]) => void }) => (
    <div data-testid="timeline-track">
      {nodes.map((node) => (
        <button key={node.chunk_id} type="button" onClick={() => onNodeClick(node)}>
          节点 {node.chunk_id}
        </button>
      ))}
    </div>
  ),
  TimelineNodeDetail: ({
    node,
    selectedRelationEventId,
  }: {
    node: TimelineResponse["nodes"][number] | null;
    selectedRelationEventId?: number | null;
  }) => (
    <div data-testid="timeline-node-detail">
      <span>{node ? `selected-${node.chunk_id}` : "selected-none"}</span>
      <span>{selectedRelationEventId != null ? `event-${selectedRelationEventId}` : "event-none"}</span>
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
    },
    phases: [
      { name: "引入期", start: 1, end: 5, ratio: 0.25 },
      { name: "发展期", start: 6, end: 10, ratio: 0.25 },
      { name: "高潮期", start: 11, end: 15, ratio: 0.25 },
      { name: "收束期", start: 16, end: 20, ratio: 0.25 },
    ],
    nodes: [
      {
        chunk_id: 8,
        progress: 0.4,
        importance_score: 5,
        level: 2,
        event: "关系变化 A",
        characters: ["顾承渊", "苏映雪"],
        is_pivot: false,
        is_cliffhanger: false,
        tension_percentile: 60,
        node_type: "relation_change",
        relation_changes: [
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
        chunk_id: 12,
        progress: 0.6,
        importance_score: 8,
        level: 1,
        event: "关系变化 B",
        characters: ["顾承渊", "苏映雪"],
        is_pivot: true,
        is_cliffhanger: false,
        tension_percentile: 90,
        node_type: "relation_change",
        relation_changes: [
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

function renderPage() {
  const queryClient = createQueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <TimelinePage />
    </QueryClientProvider>
  );
}

describe("TimelinePage deep links", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    currentTimelineSearchParams = "task_id=task-a&selected_chunk=12&relation_event_id=9002";
    useNovelStore.setState({
      currentNovelId: null,
      currentTaskId: "task-a",
      novelsCache: [],
    });
    getNovelMock.mockResolvedValue(createNovel());
    getTimelineMock.mockResolvedValue(createTimelineResponse());
  });

  it("prefers relation_event_id over selected_chunk when deep-linking from graph", async () => {
    renderPage();

    expect(await screen.findByText("selected-12")).toBeInTheDocument();
    expect(screen.getByText("event-9002")).toBeInTheDocument();
    expect(screen.queryByText("未定位到指定关系事件，已回退到对应时间节点。")).not.toBeInTheDocument();
  });

  it("falls back to selected_chunk when relation_event_id is missing", async () => {
    currentTimelineSearchParams = "task_id=task-a&selected_chunk=12&relation_event_id=9999";

    renderPage();

    expect(await screen.findByText("selected-12")).toBeInTheDocument();
    expect(screen.getByText("event-9999")).toBeInTheDocument();
    expect(screen.getByText("未定位到指定关系事件，已回退到对应时间节点。")).toBeInTheDocument();
  });

  it("clears deep-link selection when switching to another task", async () => {
    renderPage();

    await screen.findByText("selected-12");
    useNovelStore.setState({
      currentNovelId: null,
      currentTaskId: "task-b",
      novelsCache: [],
    });

    await waitFor(() => {
      expect(navigateMock).toHaveBeenCalledWith(
        "/novels/novel-1/timeline?task_id=task-b&max_level=3&show_tension=true",
        { replace: true }
      );
    });
  });
});
