import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { EventForestNode, EventForestResponse } from "@/api/types";
import { EventTreesPage } from "@/pages/EventTreesPage";
import { useNovelStore } from "@/store/novelStore";

const getEventForestMock = vi.fn();
const getEventSourceChapterMock = vi.fn();

vi.mock("@/api/results", () => ({
  getEventForest: (...args: unknown[]) => getEventForestMock(...args),
  getEventSourceChapter: (...args: unknown[]) => getEventSourceChapterMock(...args),
}));

vi.mock("@/components/layout/AnalysisWorkspace", () => ({
  AnalysisWorkspace: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}));

function node(
  eventId: string,
  treeId: string,
  description: string,
  causeRole: EventForestNode["cause_role"],
  parentEventId: string | null,
  evidenceScope: EventForestNode["evidence_scope"] = "chapter",
): EventForestNode {
  return {
    event_id: eventId, tree_id: treeId, description, cause_role: causeRole,
    parent_event_id: parentEventId, evidence_scope: evidenceScope,
    chapter_id: 1, chapter_order: 1, participants: [], anchor_paragraph_ids: [0],
    char_start: 0, char_end: 10, evidence: [{ paragraph_ids: [0] }], causal_event_refs: [],
  };
}

const forest: EventForestResponse = {
  chapter_id: 1, chapter_order: 1, visible_through_chapter_order: 1,
  derived_event_order: ["root-a", "main-a", "side-a", "root-b"],
  event_nodes: [
    node("root-a", "tree-a", "山门开启", "root", null),
    node("main-a", "tree-a", "主角入门", "main", "root-a"),
    node("side-a", "tree-a", "守卫走旁门", "secondary", "main-a", "paragraph"),
    node("root-b", "tree-b", "第二棵树", "root", null),
  ],
  event_trees: [
    { tree_id: "tree-a", root_event_id: "root-a", main_chain: ["root-a", "main-a"], secondary_groups: [{ target_event_id: "main-a", branch: ["side-a"] }], chapter_ids: [1], char_start: 0, char_end: 10 },
    { tree_id: "tree-b", root_event_id: "root-b", main_chain: ["root-b"], secondary_groups: [], chapter_ids: [1], char_start: 0, char_end: 10 },
  ],
  causal_edges: [], foreshadowing_edges: [],
};

function renderPage(url = "/novels/novel-1/event-trees?task_id=task-1") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter(
    [{ path: "/novels/:novelId/event-trees", element: <EventTreesPage /> }],
    { initialEntries: [url] },
  );
  render(<QueryClientProvider client={client}><RouterProvider router={router} /></QueryClientProvider>);
  return router;
}

beforeEach(() => {
  getEventForestMock.mockReset().mockResolvedValue(forest);
  getEventSourceChapterMock.mockReset().mockResolvedValue({
    chapter_id: 1, title: "第一章", paragraphs: [
      { paragraph_id: 0, paragraph_index: 0, text: "山门前的原文。" },
      { paragraph_id: 1, paragraph_index: 1, text: "另一段原文。" },
    ],
  });
  useNovelStore.setState({ currentNovelId: "novel-1", currentTaskId: "task-1" });
});

describe("EventTreesPage", () => {
  it("默认展现整片森林，放大真实旁支后才读取原文", async () => {
    const user = userEvent.setup();
    const router = renderPage();
    expect(await screen.findByRole("region", { name: "整片事件森林" })).toBeInTheDocument();
    expect(getEventSourceChapterMock).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: /第 1 章事件树：山门开启/ }));
    expect(screen.getByRole("region", { name: "事件树结构" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "事件树结构" }).querySelector('[data-parent-id="main-a"][data-child-id="side-a"]')).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /次因旁支.*守卫走旁门/ }));
    expect(await screen.findByText("段落级依据")).toBeInTheDocument();
    expect(router.state.location.search).toContain("tree_id=tree-a&event_id=side-a");
    await user.click(screen.getByRole("button", { name: "阅读本章原文" }));
    expect(await screen.findByRole("dialog", { name: "章节原文" })).toBeInTheDocument();
    expect(screen.getByText("山门前的原文。")).toHaveClass("bg-primary/10");
    expect(getEventSourceChapterMock).toHaveBeenCalledWith("novel-1", "task-1", 1);
  });

  it("支持深链定位和关键词筛选，无匹配时给出空状态", async () => {
    const user = userEvent.setup();
    renderPage("/novels/novel-1/event-trees?task_id=task-1&tree_id=tree-b&event_id=root-b");
    expect(await screen.findByRole("region", { name: "事件树结构" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "第二棵树" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "返回整片森林" }));
    expect(screen.getByRole("region", { name: "整片事件森林" })).toBeInTheDocument();
    await user.type(screen.getByPlaceholderText("搜索事件描述"), "不存在的情节");
    expect(screen.getByText("当前筛选下没有事件树")).toBeInTheDocument();
  });

  it("沿真实父链展示多级旁支，缺失父节点时保留待确认节点", async () => {
    getEventForestMock.mockResolvedValue({
      ...forest,
      event_nodes: [
        ...forest.event_nodes,
        node("side-child", "tree-a", "守卫随后追击", "secondary", "side-a"),
        node("side-orphan", "tree-a", "来源待确认的事件", "secondary", null),
      ],
      event_trees: [
        {
          ...forest.event_trees[0],
          secondary_groups: [
            ...forest.event_trees[0].secondary_groups,
            { target_event_id: "side-a", branch: ["side-child"] },
            { target_event_id: "tree-a", branch: ["side-orphan"] },
          ],
        },
        forest.event_trees[1],
      ],
    });
    renderPage();
    await screen.findByRole("region", { name: "整片事件森林" });
    await userEvent.setup().click(screen.getByRole("button", { name: /第 1 章事件树：山门开启/ }));
    const structure = screen.getByRole("region", { name: "事件树结构" });
    expect(structure.querySelector('[data-parent-id="side-a"][data-child-id="side-child"]')).toBeInTheDocument();
    expect(structure.querySelector('[data-child-id="side-orphan"]')).not.toBeInTheDocument();
    expect(screen.getByText(/挂接点待确认：1 个节点/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /次因旁支.*来源待确认的事件/ })).toBeInTheDocument();
  });

  it("组合章节、伏笔和旁支筛选时显示符合条件的树与空状态", async () => {
    const user = userEvent.setup();
    getEventForestMock.mockResolvedValue({
      ...forest,
      event_nodes: forest.event_nodes.map((event) => event.tree_id === "tree-b"
        ? { ...event, chapter_id: 2, chapter_order: 2 }
        : event),
      event_trees: [forest.event_trees[0], { ...forest.event_trees[1], chapter_ids: [2] }],
      foreshadowing_edges: [{
        root_event_id: "root-b", tree_id: "tree-b", payoff_event_id: null,
        first_chapter_id: 2, last_chapter_id: 2, description: "第二棵树",
        status: "open", active: true,
      }],
    });
    renderPage();
    await screen.findByRole("region", { name: "整片事件森林" });
    await user.selectOptions(screen.getByLabelText("伏笔"), "foreshadow");
    expect(screen.getByRole("region", { name: "整片事件森林" }).querySelector('[data-tree-id="tree-b"]')).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "整片事件森林" }).querySelector('[data-tree-id="tree-a"]')).not.toBeInTheDocument();
    await user.click(screen.getByLabelText("只看含旁支"));
    expect(screen.getByText("当前筛选下没有事件树")).toBeInTheDocument();
    await user.click(screen.getByLabelText("只看含旁支"));
    await user.selectOptions(screen.getByLabelText("章节"), "1");
    expect(screen.getByText("当前筛选下没有事件树")).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("伏笔"), "all");
    const restoredForest = await screen.findByRole("region", { name: "整片事件森林" });
    expect(restoredForest.querySelector('[data-tree-id="tree-a"]')).toBeInTheDocument();
    expect(restoredForest.querySelector('[data-tree-id="tree-b"]')).not.toBeInTheDocument();
  });

  it("章节筛选可深链，跨章树只归入锚定章，放大后返回仍保留章节", async () => {
    const user = userEvent.setup();
    getEventForestMock.mockResolvedValue({
      ...forest,
      event_nodes: forest.event_nodes.map((event) => event.tree_id === "tree-b"
        ? { ...event, chapter_id: 2, chapter_order: 2 }
        : event),
      event_trees: [
        { ...forest.event_trees[0], chapter_ids: [1, 2] },
        { ...forest.event_trees[1], chapter_ids: [2] },
      ],
    });
    const router = renderPage("/novels/novel-1/event-trees?task_id=task-1&chapter=2");
    const forestView = await screen.findByRole("region", { name: "整片事件森林" });
    expect(forestView.querySelector('[data-tree-id="tree-a"]')).not.toBeInTheDocument();
    expect(forestView.querySelector('[data-tree-id="tree-b"]')).toBeInTheDocument();
    await user.click(forestView.querySelector('[data-tree-id="tree-b"]') as Element);
    expect(router.state.location.search).toContain("chapter=2");
    await user.click(screen.getByRole("button", { name: "返回整片森林" }));
    expect(router.state.location.search).toBe("?task_id=task-1&chapter=2");
    expect(screen.getByLabelText("章节")).toHaveValue("2");
  });

  it("从时间轴进入没有树的章节时显示该章和筛选空状态", async () => {
    getEventForestMock.mockResolvedValue({ ...forest, visible_through_chapter_order: 3 });
    renderPage("/novels/novel-1/event-trees?task_id=task-1&chapter=3");
    expect(await screen.findByText("当前筛选下没有事件树")).toBeInTheDocument();
    expect(screen.getByLabelText("章节")).toHaveValue("3");
  });

  it("长章节可以翻到末页，关闭阅读层后仍停留在选中事件", async () => {
    const user = userEvent.setup();
    getEventSourceChapterMock.mockResolvedValue({
      chapter_id: 1, title: "第一章", paragraphs: [
        { paragraph_id: 0, paragraph_index: 0, text: `${"山门风起。".repeat(180)}章节末尾。` },
      ],
    });
    renderPage("/novels/novel-1/event-trees?task_id=task-1&tree_id=tree-a&event_id=root-a");
    await screen.findByRole("region", { name: "事件树结构" });
    await user.click(screen.getByRole("button", { name: "阅读本章原文" }));
    const next = await screen.findByRole("button", { name: "下一页" });
    expect(next).toBeEnabled();
    for (let index = 0; index < 10 && !next.hasAttribute("disabled"); index += 1) await user.click(next);
    expect(next).toBeDisabled();
    expect(screen.getByText(/章节末尾。/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "关闭原文" }));
    expect(screen.queryByRole("dialog", { name: "章节原文" })).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "山门开启" })).toBeInTheDocument();
  });
});
