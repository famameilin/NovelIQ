import { eventQueueFixture, fixtureEventDetail, selectedEventLineFixture } from "@/mocks/eventQueueFixture";
import { StrictMode, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { EventCardDetail, EventTreeEvent, EventTreeListResponse } from "@/api/narrativeTypes";
import { getEventTreeBook } from "@/api/results";
import { childEvent, eventA, eventB, grandchildEvent, installNarrativeApi, renderNarrative, tree } from "@/test/narrativeFixtures";
import { narrativeResponse } from "@/mocks/narrativeData";
import { EventTreesPage } from "@/pages/EventTreesPage";

vi.mock("@/components/layout/AnalysisWorkspace", () => ({ AnalysisWorkspace: ({ children }: { children: ReactNode }) => <main>{children}</main> }));
let api: ReturnType<typeof installNarrativeApi>;
beforeEach(() => { api = installNarrativeApi(); });
afterEach(() => vi.restoreAllMocks());
const url = "/novels/novel-1/event-trees?task_id=task-a";

it("重复挂载时不发送已取消的全书事件树和原文请求", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const router = createMemoryRouter([
    { path: "/novels/:novelId/event-trees", element: <EventTreesPage /> },
  ], { initialEntries: [url] });

  render(<StrictMode><QueryClientProvider client={client}><RouterProvider router={router} /></QueryClientProvider></StrictMode>);

  const canvas = await screen.findByLabelText("事件线画布");
  const requests = api.mock.calls.filter(([path]) => String(path).endsWith("/event-trees"));
  expect(requests).toHaveLength(1);
  await userEvent.click(within(canvas).getByRole("button", { name: eventA.title }));
  const detail = await screen.findByLabelText("事件详情");
  await waitFor(() => expect(detail).toHaveTextContent(eventA.title));
  await userEvent.click(within(detail).getByRole("button", { name: /查看完整内容/ }));
  const reader = await screen.findByRole("dialog", { name: "章节原文" });
  await waitFor(() => expect(reader).toHaveTextContent("原文 1"));
  expect(api.mock.calls.filter(([path]) => String(path).endsWith("/source"))).toHaveLength(1);
});

function themedBook(): EventTreeListResponse {
  const chapter = (order: number) => ({ chapter_id: order, chapter_order: order, title: `章节 ${order}` });
  const event = (eventId: string, title: string, order: number, kind: string): EventTreeEvent => ({
    event_id: eventId, is_event_line: false, title, problem: `${title}的核心问题`, summary: `${title}推进了故事`, event_type: kind, status: "已结束",
    from: order, to: order, chapter_id: order, chapter_order: order, first_text_position: order * 10,
  });
  const roots = [event("family-root", "贺家线", 1, "聚合"), event("court-root", "朝堂线", 2, "聚合"), event("jianghu-root", "江湖线", 3, "聚合")];
  const children = [event("family-child", "贺家变故", 1, "转折"), event("court-child", "朝堂博弈", 2, "推进"), event("jianghu-child", "江湖追杀", 3, "转折")];
  const book = eventQueueFixture({
    run_id: "run-a", chapters: [1, 2, 3].map(chapter), events: [...roots, ...children],
    edges: roots.map((root, index) => ({ parent: root.event_id, child: children[index].event_id,
      reason: "真实父子关系", evidence: [{ chapter_id: index + 1 }] })),
    outcomes: [], relations: [{ source_kind: "event", source_id: "family-child", target_kind: "event", target_id: "court-child",
      relation_type: "influence", reason: "两家与朝堂互相牵动",
      locator: { target_kind: "event", target_id: "court-child", tree_id: "tree-of-court-child", tree_position: 0,
        event_line_ids: ["tree-of-court-root"], evidence_position: 1, title: "朝堂博弈" } }],
    foreshadowing_actions: [],
  });
  return book;
}

function themedDetail(book: EventTreeListResponse, eventId: string): EventCardDetail {
  return fixtureEventDetail(book, eventId);
}

function installThemedBook() {
  const book = themedBook();
  api.mockImplementation(async (path, config) => {
    const address = String(path);
    if (address.endsWith("/event-trees")) return { data: book, status: 200 } as never;
    if (address.includes("/event-trees/nodes/") && !address.endsWith("/source")) {
      return { data: themedDetail(book, decodeURIComponent(address.split("/").at(-1)!)), status: 200 } as never;
    }
    const response = narrativeResponse(address, new URLSearchParams(Object.entries(config?.params ?? {}).map(([name, value]) => [name, String(value)])));
    return { data: response.data, status: response.status } as never;
  });
  return book;
}

it("诊断未发布时仍展示已保存事件线", async () => {
  api.mockImplementation(async (path, config) => {
    const response = narrativeResponse(String(path), new URLSearchParams(Object.entries(config?.params ?? {}).map(([name, value]) => [name, String(value)])));
    if (String(path).endsWith("/event-trees")) response.data = { ...tree, organization_status: "pending_diagnosis", next_cursor: null };
    return { data: response.data, status: response.status } as never;
  });
  renderNarrative(url);
  const canvas = await screen.findByLabelText("事件线画布");
  expect(canvas.querySelectorAll("[data-line-header]").length).toBeGreaterThan(0);
  expect(within(canvas).getByRole("button", { name: grandchildEvent.title })).toBeInTheDocument();
  expect(screen.queryByText(/需要从原文重建/)).not.toBeInTheDocument();
});

it("点击事件节点在详情面板展示概要、事件线与关联事件，并能打开原文", async () => {
  renderNarrative(url);
  const canvas = await screen.findByLabelText("事件线画布");
  await userEvent.click(within(canvas).getByRole("button", { name: eventA.title }));
  const detail = await screen.findByLabelText("事件详情");
  await waitFor(() => expect(detail).toHaveTextContent(eventA.summary));
  expect(detail).toHaveTextContent(eventA.title);
  expect(within(detail).getByRole("button", { name: new RegExp(childEvent.title) })).toBeInTheDocument();
  await userEvent.click(within(detail).getByRole("button", { name: /查看完整内容/ }));
  const reader = await screen.findByRole("dialog", { name: "章节原文" });
  await waitFor(() => expect(reader).toHaveTextContent("原文 1"));
  const calls = api.mock.calls.filter(([path]) => String(path).includes("/event-trees/nodes/"));
  expect(calls.some(([path]) => String(path).endsWith("/source"))).toBe(true);
  calls.forEach(([, config]) => expect(config?.params).toMatchObject({ task_id: "task-a" }));
});

it("事件原文保留跨章节证据切换", async () => {
  api.mockImplementation(async (path, config) => {
    const address = String(path);
    if (address.includes("/event-trees/nodes/") && address.endsWith("/source")) {
      const params = config?.params as { chapter_id?: number } | undefined;
      const chapter = Number(params?.chapter_id ?? 1);
      return { data: {
        chapter_id: chapter, title: `章节 ${chapter}`,
        paragraphs: [{ paragraph_id: chapter, paragraph_index: 0, text: `原文 ${chapter}` }],
        evidence_scope: "paragraph", evidence: [{ chapter_id: 1, paragraph_id: 1 }, { chapter_id: 2, paragraph_id: 2 }],
      }, status: 200 } as never;
    }
    const response = narrativeResponse(address, new URLSearchParams(Object.entries(config?.params ?? {}).map(([name, value]) => [name, String(value)])));
    return { data: response.data, status: response.status } as never;
  });
  renderNarrative(url);
  const canvas = await screen.findByLabelText("事件线画布");
  await userEvent.click(within(canvas).getByRole("button", { name: eventA.title }));
  const detail = await screen.findByLabelText("事件详情");
  await userEvent.click(within(detail).getByRole("button", { name: /查看完整内容/ }));
  const reader = await screen.findByRole("dialog", { name: "章节原文" });
  await waitFor(() => expect(reader).toHaveTextContent("原文 1"));
  await userEvent.selectOptions(within(reader).getByLabelText("证据章节"), "2");
  await waitFor(() => expect(reader).toHaveTextContent("原文 2"));
  await userEvent.selectOptions(within(reader).getByLabelText("证据章节"), "1");
  await waitFor(() => expect(reader).toHaveTextContent("原文 1"));
});

it("事件原文加载失败后在阅读窗口内重试", async () => {
  let failSource = true;
  api.mockImplementation(async (path, config) => {
    const address = String(path);
    if (address.includes("/event-trees/nodes/") && address.endsWith("/source") && failSource) {
      failSource = false;
      throw new Error("source unavailable");
    }
    const response = narrativeResponse(address, new URLSearchParams(Object.entries(config?.params ?? {}).map(([name, value]) => [name, String(value)])));
    return { data: response.data, status: response.status } as never;
  });
  renderNarrative(url);
  const canvas = await screen.findByLabelText("事件线画布");
  await userEvent.click(within(canvas).getByRole("button", { name: eventA.title }));
  const detail = await screen.findByLabelText("事件详情");
  await userEvent.click(within(detail).getByRole("button", { name: /查看完整内容/ }));
  const reader = await screen.findByRole("dialog", { name: "章节原文" });
  expect(within(reader).getByRole("alert")).toHaveTextContent("加载失败");
  await userEvent.click(within(reader).getByRole("button", { name: "重试" }));
  await waitFor(() => expect(screen.getByRole("dialog", { name: "章节原文" })).toHaveTextContent("原文 1"));
});

it("深链选中目标事件但不自动打开原文", async () => {
  renderNarrative(`${url}&event_id=${encodeURIComponent(grandchildEvent.event_id)}`);
  const canvas = await screen.findByLabelText("事件线画布");
  const detail = await screen.findByLabelText("事件详情");
  await waitFor(() => expect(detail).toHaveTextContent(grandchildEvent.title));
  expect(canvas.querySelector(`[data-line-node="${grandchildEvent.event_id}"]`)).toHaveAttribute("aria-pressed", "true");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it("搜索只保留命中节点，清空后恢复全部节点", async () => {
  renderNarrative(url);
  const canvas = await screen.findByLabelText("事件线画布");
  const node = () => canvas.querySelector(`[data-line-node="${eventA.event_id}"]`)!;
  expect(node()).toHaveAttribute("data-line-node-dimmed", "false");
  await userEvent.type(screen.getByLabelText("搜索事件"), "查无此事");
  await waitFor(() => expect(node()).toHaveAttribute("data-line-node-dimmed", "true"));
  await userEvent.clear(screen.getByLabelText("搜索事件"));
  await waitFor(() => expect(node()).toHaveAttribute("data-line-node-dimmed", "false"));
});

it("关联线开关控制节点间虚线，缩放与适应画布更新显示比例", async () => {
  installThemedBook();
  renderNarrative(url);
  const canvas = await screen.findByLabelText("事件线画布");
  await userEvent.click(within(canvas).getByRole("button", { name: "贺家变故" }));
  await waitFor(() => expect(canvas.querySelectorAll("[data-line-relation]")).toHaveLength(1));
  await userEvent.click(screen.getByRole("switch", { name: /显示关联线/ }));
  await waitFor(() => expect(canvas.querySelectorAll("[data-line-relation]")).toHaveLength(0));
  await userEvent.click(screen.getByRole("switch", { name: /显示关联线/ }));
  expect(canvas.querySelectorAll("[data-line-relation]")).toHaveLength(1);
  await userEvent.click(screen.getByRole("button", { name: "放大" }));
  expect(screen.getByText("110%")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "适应画布" }));
  expect(screen.getByText("100%")).toBeInTheDocument();
});

it("目录视图按事件线列出全部事件并打开详情", async () => {
  renderNarrative(url);
  await screen.findByLabelText("事件线画布");
  await userEvent.selectOptions(screen.getByLabelText("视图样式"), "directory");
  const directory = await screen.findByLabelText("事件目录");
  expect(within(directory).getByRole("button", { name: new RegExp(eventA.title) })).toBeInTheDocument();
  await userEvent.click(within(directory).getByRole("button", { name: new RegExp(grandchildEvent.title) }));
  const detail = screen.getByLabelText("事件详情");
  await waitFor(() => expect(detail).toHaveTextContent(grandchildEvent.title));
  expect(screen.queryByLabelText("事件线画布")).not.toBeInTheDocument();
});

it("全书响应缺失事件时明确读取失败，不合并其他请求补齐", async () => {
  api.mockImplementationOnce(async () => ({ data: { ...tree, events: [eventA] } }) as never);
  await expect(getEventTreeBook("novel-1", "task-a")).rejects.toThrow("响应不完整");
  expect(api).toHaveBeenCalledTimes(1);
});

it("低覆盖结果保持正式入口与全部事件计数，未覆盖事件深链仍能读取详情", async () => {
  const book = selectedEventLineFixture();
  api.mockImplementation(async (path, config) => {
    const address = String(path);
    if (address.endsWith("/event-trees")) return { data: book, status: 200 } as never;
    if (address.includes("/event-trees/nodes/") && !address.endsWith("/source")) {
      return { data: fixtureEventDetail(book, decodeURIComponent(address.split("/").at(-1)!)), status: 200 } as never;
    }
    const response = narrativeResponse(address, new URLSearchParams(Object.entries(config?.params ?? {}).map(([name, value]) => [name, String(value)])));
    return { data: response.data, status: response.status } as never;
  });
  renderNarrative(`${url}&event_id=uncovered-9`);
  const canvas = await screen.findByLabelText("事件线画布");
  expect(canvas.querySelectorAll("[data-line-header]")).toHaveLength(5);
  expect(screen.getByLabelText("事件数")).toHaveTextContent("20");
  expect(canvas.querySelector('[data-line-header="tree-of-a0"]')).not.toBeNull();
  await waitFor(() => expect(screen.getByLabelText("事件详情")).toHaveTextContent("事件 uncovered-9"));
  expect(screen.queryByText(/响应不完整/)).not.toBeInTheDocument();
});

it("旧过程参数不触发原文读取或事件卡", async () => {
  renderNarrative(`${url}&process_id=process%3Aa`);
  await screen.findByLabelText("事件线画布");
  await screen.findByLabelText("事件详情");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(api.mock.calls.filter(([path]) => String(path).includes("process%3Aa/source"))).toHaveLength(0);
  expect(api.mock.calls.filter(([path]) => String(path).includes("nodes/process"))).toHaveLength(0);
  expect(screen.getByLabelText("事件详情")).not.toHaveTextContent(eventB.title);
});
