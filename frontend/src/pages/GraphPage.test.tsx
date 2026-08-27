import { createElement } from "react";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  GraphChangesPageResponse,
  GraphData,
  Novel,
} from "@/api/types";
import type { GraphNodeObject } from "@/components/charts/forceGraphTypes";
import { GraphPage } from "@/pages/GraphPage";
import { useNovelStore } from "@/store/novelStore";

const getGraphMock = vi.fn();
const getCharactersMock = vi.fn();
const getGraphChangesMock = vi.fn();
const getNovelMock = vi.fn();
const navigateMock = vi.fn();

let currentGraphSearchParams = "task_id=task-a";

// 2026-08-07 用于在页面测试中消除动画运行时差异
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
  useParams: () => ({ novelId: "novel-1" }),
  useSearchParams: () => [new URLSearchParams(currentGraphSearchParams)],
}));

vi.mock("framer-motion", () => ({
  AnimatePresence: ({ children }: { children?: ReactNode }) => <>{children}</>,
  motion: new Proxy({}, { get: (_target, key: string) => motionElement(key) }),
}));

vi.mock("@/components/common/NovelHeader", () => ({
  NovelHeader: ({ title }: { title: string }) => <div>{title}</div>,
}));

vi.mock("@/components/layout/AnalysisWorkspace", () => ({
  AnalysisWorkspace: Object.assign(
    ({ children }: { children?: ReactNode }) => <div>{children}</div>,
    {
      Tabs: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
      Tab: ({ children }: { children?: ReactNode }) => <section>{children}</section>,
    },
  ),
}));

vi.mock("@/components/ui/tooltip", () => ({
  Tooltip: ({ children }: { children?: ReactNode }) => <>{children}</>,
  TooltipContent: ({ children }: { children?: ReactNode }) => <>{children}</>,
  TooltipProvider: ({ children }: { children?: ReactNode }) => <>{children}</>,
  TooltipTrigger: ({ children }: { children?: ReactNode }) => <>{children}</>,
}));

vi.mock("@/components/charts/ForceGraph", () => ({
  ForceGraph: ({
    data,
    onNodeClick,
  }: {
    data: GraphData;
    onNodeClick: (node: GraphNodeObject) => void;
  }) => (
    <button
      type="button"
      onClick={() => {
        const node = data.nodes[0];
        if (node) {
          onNodeClick({ ...node, id: String(node.entity_id) });
        }
      }}
    >
      选择第一个节点
    </button>
  ),
}));

vi.mock("@/components/charts/GraphToolbar", () => ({
  GraphToolbar: () => <div>图谱工具栏</div>,
}));

vi.mock("@/components/charts/GraphLegend", () => ({
  GraphLegend: () => <div>图谱图例</div>,
}));

vi.mock("@/components/charts/NodeDetailPanel", () => ({
  NodeDetailPanel: ({ node }: { node: GraphData["nodes"][number] | null }) => (
    <div>{node ? `selected-node:${node.name}` : "selected-node:none"}</div>
  ),
}));

vi.mock("@/api/results", () => ({
  getGraph: (...args: unknown[]) => getGraphMock(...args),
  getCharacters: (...args: unknown[]) => getCharactersMock(...args),
  getGraphChanges: (...args: unknown[]) => getGraphChangesMock(...args),
}));

vi.mock("@/api/novels", () => ({
  getNovel: (...args: unknown[]) => getNovelMock(...args),
}));

// 2026-08-07 用于构造章节图快照页面测试数据
function createGraphData(): GraphData {
  return {
    chapter_id: 3,
    chapter_order: 3,
    first_chapter_id: 11,
    last_chapter_id: 15,
    nodes: [
      {
        entity_id: 1,
        name: "顾霜",
        entity_type: "character",
        first_seen_chapter: 1,
        last_seen_chapter: 15,
        state_chapter_id: 3,
        state: { primary_role_function: "主角", status: "active" },
      },
      {
        entity_id: 2,
        name: "司夜",
        entity_type: "character",
        first_seen_chapter: 2,
        last_seen_chapter: 15,
        state_chapter_id: 3,
        state: {},
      },
    ],
    edges: [
      {
        relation_id: "relation-1",
        state_chapter_id: 3,
        source_entity_id: 1,
        target_entity_id: 2,
        source_name: "顾霜",
        target_name: "司夜",
        relation_type: "盟友",
        directionality: "bidirectional",
        relation_semantics: "ordinary",
        attributes: {},
        is_active: true,
        changes: [],
      },
    ],
  };
}

// 2026-08-07 用于构造图谱变化分页页面测试数据
function createGraphChangesPage(): GraphChangesPageResponse {
  return {
    changes: [
      {
        change_id: "relation:12:1",
        change_kind: "relation",
        chapter_id: 3,
        chapter_order: 3,
        fact_id: "fact-12",
        effective_chapter_id: 12,
        changes: [{ change_kind: "assert" }],
        relation_id: "relation-1",
        from_entity_id: 1,
        to_entity_id: 2,
        from_name: "顾霜",
        to_name: "司夜",
        relation_type: "盟友",
        relation_change_kind: "assert",
        directionality: "bidirectional",
        relation_semantics: "ordinary",
      },
      {
        change_id: "state:13:1",
        change_kind: "state",
        chapter_id: 3,
        chapter_order: 3,
        fact_id: "fact-13",
        effective_chapter_id: 13,
        changes: [{ field: "status", before: "hidden", after: "active" }],
        entity_id: 1,
        entity_name: "顾霜",
      },
    ],
    page_info: {
      limit: 200,
      returned_count: 2,
      total: 2,
      has_more: false,
      next_cursor: null,
    },
  };
}

// 2026-08-07 用于提供隔离的 GraphPage 查询缓存
function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <GraphPage />
    </QueryClientProvider>,
  );
}

describe("GraphPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    currentGraphSearchParams = "task_id=task-a";
    useNovelStore.setState({ currentNovelId: null, currentTaskId: null, novelsCache: [] });
    getGraphMock.mockResolvedValue(createGraphData());
    getCharactersMock.mockResolvedValue([{ name: "顾霜", appearance_count: 4 }]);
    getGraphChangesMock.mockResolvedValue(createGraphChangesPage());
    getNovelMock.mockResolvedValue({
      novel_id: "novel-1",
      title: "图谱测试小说",
      filename: "graph.txt",
      author: "测试",
      upload_time: "2026-08-07T00:00:00Z",
      file_size: 1,
    } satisfies Novel);
  });

  it("读取章节快照并独立加载实体与关系变化", async () => {
    renderPage();

    expect((await screen.findAllByText(/第 13 章 · 顾霜/)).length).toBeGreaterThan(0);
    expect(screen.getByText(/第 12 章 · 顾霜 → 司夜/)).toBeInTheDocument();
    expect(screen.getByText("盟友 · 建立")).toBeInTheDocument();
    expect(getGraphChangesMock).toHaveBeenCalledWith("novel-1", "task-a");
  });

  it("使用稳定 change_id 记录图谱变化选择", async () => {
    const user = userEvent.setup();
    renderPage();

    const relationChange = await screen.findByText(/第 12 章 · 顾霜 → 司夜/);
    await user.click(relationChange.closest("button")!);

    expect(navigateMock).toHaveBeenCalledWith(
      "/novels/novel-1/graph?task_id=task-a&selected_chapter=12&change_id=relation%3A12%3A1",
      { replace: true },
    );
  });
});
