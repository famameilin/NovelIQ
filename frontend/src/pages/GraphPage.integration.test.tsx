import { createElement, forwardRef, useImperativeHandle } from "react";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { GraphData, Novel } from "@/api/types";
import { TooltipProvider } from "@/components/ui/tooltip";
import { GraphPage } from "@/pages/GraphPage";
import { useNovelStore } from "@/store/novelStore";

const getGraphMock = vi.fn();
const getCharactersMock = vi.fn();
const getGraphEventsMock = vi.fn();
const getNovelMock = vi.fn();
const getAnalysisTasksMock = vi.fn();
const navigateMock = vi.fn();

let currentGraphSearchParams = "task_id=task-integration";
let currentGraphNovelId = "novel-1";

// 2026-04-23，任务：复杂度与耦合审查 P2。测试里只替换动画壳，保留真实页面子组件组合。
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
  useParams: () => ({ novelId: currentGraphNovelId }),
  useSearchParams: () => [new URLSearchParams(currentGraphSearchParams)],
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

vi.mock("@/components/ui/dropdown-menu", () => ({
  DropdownMenu: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
  DropdownMenuCheckboxItem: ({
    children,
    onCheckedChange,
  }: {
    children?: ReactNode;
    onCheckedChange?: () => void;
  }) => (
    <button type="button" onClick={onCheckedChange}>
      {children}
    </button>
  ),
  DropdownMenuContent: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
  DropdownMenuLabel: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
  DropdownMenuSeparator: () => <hr />,
  DropdownMenuTrigger: ({ children }: { children?: ReactNode }) => <>{children}</>,
}));

vi.mock("@/components/charts/ForceGraph", () => ({
  ForceGraph: forwardRef(
    (
      {
        data,
        onNodeClick,
        searchQuery,
        relationFilter,
      }: {
        data?: GraphData;
        onNodeClick?: (node: GraphData["nodes"][number]) => void;
        searchQuery?: string;
        relationFilter?: Set<string>;
      },
      ref
    ) => {
      useImperativeHandle(ref, () => ({
        zoomIn: vi.fn(),
        zoomOut: vi.fn(),
        fitToScreen: vi.fn(),
        center: vi.fn(),
      }));
      return (
        <div data-testid="integration-force-graph">
          <span>{`search:${searchQuery || "none"}`}</span>
          <span>{`relations:${relationFilter?.size ?? 0}`}</span>
          <button type="button" onClick={() => data?.nodes[0] && onNodeClick?.(data.nodes[0])}>
            选择顾承渊
          </button>
        </div>
      );
    }
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

vi.mock("@/api/analysis", () => ({
  batchDeleteTasks: vi.fn(),
  cancelAnalysisTask: vi.fn(),
  getAnalysisTasks: (...args: unknown[]) => getAnalysisTasksMock(...args),
}));

// 2026-04-23，任务：复杂度与耦合审查 P2。创建独立 QueryClient，避免页面集成测试间缓存串扰。
function renderGraphPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <GraphPage />
      </TooltipProvider>
    </QueryClientProvider>
  );
}

// 2026-04-23，任务：复杂度与耦合审查 P2。复用真实 GraphPage 需要的最小完整图谱合约。
function createGraphData(): GraphData {
  return {
    nodes: [
      {
        entity_id: "hero",
        name: "顾承渊",
        entity_type: "character",
        first_seen_chunk: 1,
        last_seen_chunk: 12,
        role: "protagonist",
        status: "active",
      },
      {
        entity_id: "ally",
        name: "苏映雪",
        entity_type: "character",
        first_seen_chunk: 2,
        last_seen_chunk: 12,
        role: "supporting",
        status: "active",
      },
    ],
    edges: [
      {
        source: "hero",
        target: "ally",
        relation_type: "盟友",
        weight: 2,
        from_name: "顾承渊",
        to_name: "苏映雪",
        change_count: 1,
        tension_index: 0,
        is_active: true,
      },
    ],
    events: [
      {
        relation_event_id: 31,
        chunk_id: 8,
        from_entity_id: 1,
        to_entity_id: 2,
        from_name: "顾承渊",
        to_name: "苏映雪",
        relation_type: "盟友",
        change_type: "新建",
        evidence: "顾承渊与苏映雪联手查案。",
        confidence: 0.88,
        source_relation_row_id: 31,
        directionality: "bidirectional",
      },
    ],
    events_page: {
      limit: 200,
      returned_count: 1,
      total: 1,
      has_more: false,
      next_cursor: null,
    },
    summary: {
      node_count: 2,
      edge_count: 1,
      density: 0.5,
      core_characters: ["顾承渊", "苏映雪"],
      key_relations: [{ from: "顾承渊", to: "苏映雪", type: "盟友", support_count: 1 }],
    },
    quality: {
      conflict_count: 0,
      low_confidence_count: 0,
      conflicts: [],
      low_confidence_samples: [],
    },
  };
}

// 2026-04-23，任务：复杂度与耦合审查 P2。构造真实 NovelHeader 查询所需小说对象。
function createNovel(): Novel {
  return {
    novel_id: "novel-1",
    title: "Graph Integration Novel",
    filename: "graph.txt",
    author: "Tester",
    upload_time: "2026-04-23T00:00:00Z",
    file_size: 1,
  };
}

describe("GraphPage integration", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    currentGraphSearchParams = "task_id=task-integration";
    currentGraphNovelId = "novel-1";
    useNovelStore.setState({ currentNovelId: null, currentTaskId: null, novelsCache: [] });
    getNovelMock.mockResolvedValue(createNovel());
    getAnalysisTasksMock.mockResolvedValue([]);
    getCharactersMock.mockResolvedValue([{ name: "顾承渊", appearance_count: 5 }]);
    getGraphMock.mockResolvedValue(createGraphData());
  });

  it("wires the real toolbar and node detail panel through the page", async () => {
    const user = userEvent.setup();
    renderGraphPage();

    await screen.findByText("关系工作区");
    await user.type(screen.getByPlaceholderText("搜索节点..."), "顾");

    expect(screen.getByText("search:顾")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "选择顾承渊" }));

    expect(await screen.findByText("关联角色")).toBeInTheDocument();
    expect(screen.getAllByText("顾承渊").length).toBeGreaterThan(0);
    expect(screen.getAllByText("苏映雪").length).toBeGreaterThan(0);
  });
});
