import { createElement } from "react";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Novel, TimelineResponse } from "@/api/types";
import { TooltipProvider } from "@/components/ui/tooltip";
import { TimelinePage } from "@/pages/TimelinePage";
import { useNovelStore } from "@/store/novelStore";

const getTimelineMock = vi.fn();
const getNovelMock = vi.fn();
const getAnalysisTasksMock = vi.fn();
const navigateMock = vi.fn();

let currentTimelineSearchParams = "task_id=task-integration&selected_chunk=8&relation_event_id=31";
let currentTimelineNovelId = "novel-1";

// 2026-04-23，任务：复杂度与耦合审查 P2。集成测试保留真实 timeline 组件，仅替换动画属性
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

vi.mock("@/components/ui/tooltip", () => ({
  Tooltip: ({ children }: { children?: ReactNode }) => <>{children}</>,
  TooltipContent: ({ children }: { children?: ReactNode }) => <span>{children}</span>,
  TooltipProvider: ({ children }: { children?: ReactNode }) => <>{children}</>,
  TooltipTrigger: ({ children }: { children?: ReactNode }) => <>{children}</>,
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

// 2026-04-23，任务：复杂度与耦合审查 P2。创建独立 QueryClient，验证页面级组件真实组合
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

// 2026-04-23，任务：复杂度与耦合审查 P2。构造含 relation node 的时间轴响应，覆盖图谱联动路径
function createTimelineResponse(): TimelineResponse {
  return {
    meta: {
      novel_id: "novel-1",
      novel_name: "Timeline Integration Novel",
      total_chunks: 12,
    },
    phases: [
      { name: "引入期", start: 1, end: 3, ratio: 0.25 },
      { name: "发展期", start: 4, end: 6, ratio: 0.25 },
      { name: "高潮期", start: 7, end: 9, ratio: 0.25 },
      { name: "收束期", start: 10, end: 12, ratio: 0.25 },
    ],
    composite_nodes: [
      {
        node_id: "composite:relation:8:0",
        anchor_chunk_id: 8,
        start_chunk_id: 8,
        end_chunk_id: 8,
        progress: 0.66,
        start_progress: 0.66,
        end_progress: 0.66,
        importance_score: 9,
        level: 1,
        summary: "顾承渊与苏映雪结盟",
        characters: ["顾承渊", "苏映雪"],
        phase_name: "高潮期",
        node_type: "relation",
        node_subtypes: ["新建"],
        representative_node_id: "relation:31",
        child_node_ids: ["relation:31"],
      },
    ],
    atomic_nodes: [
      {
        node_id: "relation:31",
        anchor_chunk_id: 8,
        progress: 0.66,
        importance_score: 9,
        level: 1,
        summary: "顾承渊与苏映雪结盟",
        characters: ["顾承渊", "苏映雪"],
        phase_name: "高潮期",
        node_type: "relation",
        node_subtype: "新建",
        score_breakdown: { change_type_weight: 2.4, pair_importance: 1.6 },
        plot_flags: {
          is_pivot: true,
          is_cliffhanger: false,
          tension_percentile: 82,
        },
        relation_events: [
          {
            relation_event_id: 31,
            from_char: "顾承渊",
            to_char: "苏映雪",
            relation_type: "盟友",
            change_type: "新建",
          },
        ],
      },
    ],
    tension_curve: [0.2, 0.45, 0.8],
  };
}

// 2026-04-27，任务：fix-timeline-selected-node-relation-event-conflict
// 构造两个 relation 节点，验证 selected_node_id 与 relation_event_id 冲突时页面不会把错误事件带回图谱
function createConflictingTimelineResponse(): TimelineResponse {
  return {
    ...createTimelineResponse(),
    composite_nodes: [
      ...(createTimelineResponse().composite_nodes ?? []),
      {
        node_id: "composite:relation:9:0",
        anchor_chunk_id: 9,
        start_chunk_id: 9,
        end_chunk_id: 9,
        progress: 0.75,
        start_progress: 0.75,
        end_progress: 0.75,
        importance_score: 7,
        level: 1,
        summary: "顾承渊与陆沉反目",
        characters: ["顾承渊", "陆沉"],
        phase_name: "高潮期",
        node_type: "relation",
        node_subtypes: ["断裂"],
        representative_node_id: "relation:32",
        child_node_ids: ["relation:32"],
      },
    ],
    atomic_nodes: [
      ...(createTimelineResponse().atomic_nodes ?? []),
      {
        node_id: "relation:32",
        anchor_chunk_id: 9,
        progress: 0.75,
        importance_score: 7,
        level: 1,
        summary: "顾承渊与陆沉反目",
        characters: ["顾承渊", "陆沉"],
        phase_name: "高潮期",
        node_type: "relation",
        node_subtype: "断裂",
        score_breakdown: { change_type_weight: 2.1, pair_importance: 1.3 },
        relation_events: [
          {
            relation_event_id: 32,
            from_char: "顾承渊",
            to_char: "陆沉",
            relation_type: "对手",
            change_type: "断裂",
          },
        ],
      },
    ],
  };
}

// 2026-04-23，任务：复杂度与耦合审查 P2。构造真实 NovelHeader 查询所需小说对象
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

describe("TimelinePage integration", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    currentTimelineSearchParams = "task_id=task-integration&selected_chunk=8&relation_event_id=31";
    currentTimelineNovelId = "novel-1";
    useNovelStore.setState({ currentNovelId: null, currentTaskId: null, novelsCache: [] });
    getNovelMock.mockResolvedValue(createNovel());
    getAnalysisTasksMock.mockResolvedValue([]);
    getTimelineMock.mockResolvedValue(createTimelineResponse());
  });

  it("keeps graph deep-link state through real timeline controls and detail actions", async () => {
    const user = userEvent.setup();
    renderTimelinePage();

    expect((await screen.findAllByText("顾承渊与苏映雪结盟")).length).toBeGreaterThan(0);
    await user.click(screen.getByRole("button", { name: "重要" }));

    expect(navigateMock).toHaveBeenCalledWith(
      "/novels/novel-1/timeline?task_id=task-integration&max_level=1&view=composite&selected_node_id=relation%3A31&selected_chunk=8&relation_event_id=31",
      { replace: true }
    );

    await user.click(screen.getByRole("button", { name: /回到图谱入口/ }));
    expect(navigateMock).toHaveBeenCalledWith("/novels/novel-1/graph?task_id=task-integration&selected_chunk=8&relation_event_id=31");
  });

  it("does not carry a conflicting relation_event_id back to graph when selected_node_id points elsewhere", async () => {
    currentTimelineSearchParams = "task_id=task-integration&selected_node_id=relation%3A31&selected_chunk=8&relation_event_id=32";
    getTimelineMock.mockResolvedValue(createConflictingTimelineResponse());
    const user = userEvent.setup();

    renderTimelinePage();

    expect((await screen.findAllByText("顾承渊与苏映雪结盟")).length).toBeGreaterThan(0);
    await user.click(screen.getByRole("button", { name: /回到图谱入口/ }));

    expect(navigateMock).toHaveBeenCalledWith("/novels/novel-1/graph?task_id=task-integration&selected_chunk=8&relation_event_id=31");
  });
});
