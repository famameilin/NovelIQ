import { createElement } from "react";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { GraphChangesPageResponse, GraphData, Novel } from "@/api/types";
import { TooltipProvider } from "@/components/ui/tooltip";
import { GraphPage } from "@/pages/GraphPage";
import { useNovelStore } from "@/store/novelStore";

const getGraphMock = vi.fn();
const getCharactersMock = vi.fn();
const getGraphChangesMock = vi.fn();
const getNovelMock = vi.fn();
const navigateMock = vi.fn();

// 2026-08-07 用于在图谱集成测试中消除动画运行时差异
function motionElement(tagName: string) {
  const Component = (props: { children?: ReactNode; [key: string]: unknown }) => {
    const sanitizedProps = { ...props };
    ["whileHover", "whileTap", "transition", "variants", "initial", "animate", "exit"].forEach((key) => {
      delete sanitizedProps[key];
    });
    return createElement(tagName, sanitizedProps, props.children);
  };
  Component.displayName = `motion-${tagName}`;
  return Component;
}

vi.mock("react-router-dom", () => ({
  useNavigate: () => navigateMock,
  useParams: () => ({ novelId: "novel-1" }),
  useSearchParams: () => [new URLSearchParams("task_id=task-integration")],
}));

vi.mock("framer-motion", () => ({
  AnimatePresence: ({ children }: { children?: ReactNode }) => <>{children}</>,
  motion: new Proxy({}, { get: (_target, key: string) => motionElement(key) }),
}));

vi.mock("@/components/charts/ForceGraph", () => ({
  ForceGraph: ({ data, onNodeClick }: { data: GraphData; onNodeClick: (node: GraphData["nodes"][number]) => void }) => {
    const firstNode = data.nodes[0];
    return (
      <button type="button" onClick={() => firstNode && onNodeClick(firstNode)}>
        选择顾霜
      </button>
    );
  },
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

vi.mock("@/components/charts/GraphToolbar", () => ({
  GraphToolbar: () => <div>图谱工具栏</div>,
}));

vi.mock("@/components/charts/GraphLegend", () => ({
  GraphLegend: () => <div>图谱图例</div>,
}));

vi.mock("@/api/results", () => ({
  getGraph: (...args: unknown[]) => getGraphMock(...args),
  getCharacters: (...args: unknown[]) => getCharactersMock(...args),
  getGraphChanges: (...args: unknown[]) => getGraphChangesMock(...args),
}));

vi.mock("@/api/novels", () => ({
  getNovel: (...args: unknown[]) => getNovelMock(...args),
}));

vi.mock("@/api/analysis", () => ({
  batchDeleteTasks: vi.fn(),
  cancelAnalysisTask: vi.fn(),
  getAnalysisTasks: vi.fn().mockResolvedValue([]),
}));

// 2026-08-07 用于构造真实图谱工作区所需的最小章节快照
function createGraphData(): GraphData {
  return {
    graph_version_id: "graph-version-1",
    chapter_id: 1,
    chapter_order: 1,
    first_chapter_id: 1,
    last_chapter_id: 8,
    nodes: [
      {
        entity_id: 1,
        name: "顾霜",
        entity_type: "character",
        first_seen_chapter: 1,
        last_seen_chapter: 8,
        state_revision: 1,
        state: { primary_role_function: "主角" },
      },
      {
        entity_id: 2,
        name: "苏映雪",
        entity_type: "character",
        first_seen_chapter: 2,
        last_seen_chapter: 8,
        state_revision: 1,
        state: {},
      },
    ],
    edges: [
      {
        relation_id: "relation-1",
        relation_version_id: 1,
        relation_revision: 1,
        source_entity_id: 1,
        target_entity_id: 2,
        source_name: "顾霜",
        target_name: "苏映雪",
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

// 2026-08-07 用于构造图谱变化面板所需的最小分页结果
function createGraphChanges(): GraphChangesPageResponse {
  return {
    changes: [],
    page_info: { limit: 200, returned_count: 0, total: 0, has_more: false, next_cursor: null },
  };
}

// 2026-08-07 用于渲染包含真实图谱页面子组件的集成用例
function renderGraphPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <GraphPage />
      </TooltipProvider>
    </QueryClientProvider>,
  );
}

describe("GraphPage integration", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useNovelStore.setState({ currentNovelId: null, currentTaskId: null, novelsCache: [] });
    getGraphMock.mockResolvedValue(createGraphData());
    getCharactersMock.mockResolvedValue([{ name: "顾霜", appearance_count: 5 }]);
    getGraphChangesMock.mockResolvedValue(createGraphChanges());
    getNovelMock.mockResolvedValue({
      novel_id: "novel-1",
      title: "图谱集成测试小说",
      filename: "graph.txt",
      author: "测试",
      upload_time: "2026-08-07T00:00:00Z",
      file_size: 1,
    } satisfies Novel);
  });

  it("把真实工具栏、画布和节点详情串在章节快照上", async () => {
    const user = userEvent.setup();
    renderGraphPage();

    expect(await screen.findByText("关系工作区")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "选择顾霜" }));

    expect(await screen.findByText("关联角色")).toBeInTheDocument();
    expect(screen.getAllByText("顾霜").length).toBeGreaterThan(0);
    expect(screen.getAllByText("苏映雪").length).toBeGreaterThan(0);
  });
});
