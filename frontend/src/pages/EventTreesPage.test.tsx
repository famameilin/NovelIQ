import type { ReactNode } from "react";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { childEvent, eventA, eventB, grandchildEvent, installNarrativeApi, renderNarrative, tree } from "@/test/narrativeFixtures";
import { getEventTreeBook } from "@/api/results";
import { narrativeResponse } from "@/mocks/narrativeData";

vi.mock("@/components/layout/AnalysisWorkspace", () => ({ AnalysisWorkspace: ({ children }: { children: ReactNode }) => <main>{children}</main> }));
let api: ReturnType<typeof installNarrativeApi>;
beforeEach(() => { api = installNarrativeApi(); });
afterEach(() => vi.restoreAllMocks());
const url = "/novels/novel-1/event-trees?task_id=task-a";
const key = "novel-1:run-a:event-trees";

it("事件声明保存但诊断未发布时显示阶段提示", async () => {
  api.mockImplementation(async (path, config) => {
    const response = narrativeResponse(String(path), new URLSearchParams(Object.entries(config?.params ?? {}).map(([name, value]) => [name, String(value)])));
    if (String(path).endsWith("/event-trees")) {
      response.data = { ...tree, organization_status: "pending_diagnosis", events: [], next_cursor: null,
        counts: { ...tree.counts, top_level_events: 0, child_events: 0, all_events: 0 } };
    }
    return { data: response.data, status: response.status } as never;
  });
  renderNarrative(url);
  expect(await screen.findByText("事件声明已保存，等待诊断确认全书事件树")).toBeInTheDocument();
  expect(screen.queryByLabelText("事件树画布")).not.toBeInTheDocument();
  expect(screen.queryByText(/需要从原文重建/)).not.toBeInTheDocument();
});

it("完整消费分页，只为顶层事件绘制入口，结果和叙事线不可点击", async () => {
  renderNarrative(url);
  const canvas = await screen.findByLabelText("事件树画布");
  expect(within(canvas).getAllByRole("button")).toHaveLength(2);
  expect(within(canvas).getByRole("button", { name: eventB.title })).toBeInTheDocument();
  expect(canvas.querySelectorAll("[data-outcome-id]")).toHaveLength(1);
  expect(canvas.querySelectorAll("[data-arc-anchor]")).toHaveLength(1);
  expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /缩放|适应|力导向/ })).not.toBeInTheDocument();
  const calls = api.mock.calls.filter(([path]) => String(path).endsWith("/event-trees"));
  expect(calls).toHaveLength(2);
  expect(calls[1][1]?.params.cursor).toBe("second");
  calls.forEach(([, config]) => expect(Object.keys(config!.params).sort()).toEqual(config!.params.cursor ? ["cursor", "limit", "task_id"] : ["limit", "task_id"]));
});

it("统一事件卡逐级打开直接子事件，父卡保留且独立关闭", async () => {
  renderNarrative(url);
  await userEvent.click(await screen.findByRole("button", { name: eventA.title }));
  const parent = await screen.findByRole("dialog", { name: `事件详情：${eventA.title}` });
  expect(parent).toHaveTextContent("所属主线");
  expect(parent).toHaveTextContent("林舟");
  expect(parent).not.toHaveTextContent(grandchildEvent.title);
  await userEvent.click(within(parent).getByRole("button", { name: new RegExp(childEvent.title) }));
  const child = await screen.findByRole("dialog", { name: `事件详情：${childEvent.title}` });
  expect(parent).toBeInTheDocument();
  await userEvent.click(within(child).getByRole("button", { name: new RegExp(grandchildEvent.title) }));
  await screen.findByRole("dialog", { name: `事件详情：${grandchildEvent.title}` });
  expect(screen.getAllByRole("dialog")).toHaveLength(3);
  await userEvent.click(within(child).getByRole("button", { name: "关闭事件卡" }));
  expect(parent).toBeInTheDocument();
  expect(screen.getAllByRole("dialog")).toHaveLength(2);
});

it("画布滚轮不移动或缩放，拖动只写X，卡片正文可复制", async () => {
  renderNarrative(url);
  const canvas = await screen.findByLabelText("事件树画布");
  Object.defineProperty(canvas, "setPointerCapture", { value: vi.fn() });
  const before = (canvas.firstElementChild as HTMLElement).style.transform;
  const wheel = new WheelEvent("wheel", { bubbles: true, cancelable: true, deltaX: 120, deltaY: -120 });
  fireEvent(canvas, wheel);
  expect(wheel.defaultPrevented).toBe(true);
  expect((canvas.firstElementChild as HTMLElement).style.transform).toBe(before);
  fireEvent(canvas, new MouseEvent("pointerdown", { bubbles: true, button: 0, clientX: 200, clientY: 180 }));
  fireEvent(canvas, new MouseEvent("pointermove", { bubbles: true, clientX: 160, clientY: 280 }));
  fireEvent(canvas, new MouseEvent("pointerup", { bubbles: true }));
  // 全部内容已入框时平移边界夹紧为零，长篇实际位移另由浏览器规模用例验证
  await waitFor(() => expect(JSON.parse(localStorage.getItem(key)!).x).toBe(0));
  expect(JSON.parse(localStorage.getItem(key)!)).not.toHaveProperty("y");
  expect(JSON.parse(localStorage.getItem(key)!)).not.toHaveProperty("scale");
  await userEvent.click(within(canvas).getByRole("button", { name: eventA.title }));
  const card = await screen.findByRole("dialog", { name: `事件详情：${eventA.title}` });
  const body = card.querySelector("[data-card-body]")!;
  expect(body.closest(".select-none")).toBeNull();
  const range = document.createRange(); range.selectNodeContents(body);
  window.getSelection()!.removeAllRanges(); window.getSelection()!.addRange(range);
  expect(window.getSelection()!.toString()).toContain(eventA.summary);
});

it("子事件深链沿正式祖先打开卡片，画布仍只有大事件", async () => {
  renderNarrative(`${url}&event_id=${encodeURIComponent(grandchildEvent.event_id)}`);
  await screen.findByRole("dialog", { name: `事件详情：${grandchildEvent.title}` });
  expect(screen.getAllByRole("dialog")).toHaveLength(3);
  expect(screen.getByLabelText("事件树画布").querySelectorAll("[data-event-marker]")).toHaveLength(2);
});

it("目录真实关系跳转沿包含路径打开子卡", async () => {
  renderNarrative(url);
  await userEvent.click(await screen.findByRole("button", { name: eventA.title }));
  await screen.findByRole("dialog", { name: `事件详情：${eventA.title}` });
  await userEvent.click(screen.getByRole("button", { name: "结构目录" }));
  await userEvent.click(within(screen.getByLabelText("结构目录")).getByRole("button", { name: new RegExp(childEvent.title) }));
  await screen.findByRole("dialog", { name: `事件详情：${childEvent.title}` });
  expect(screen.getAllByRole("dialog")).toHaveLength(2);
});

it("失败页和跨运行分页明确失败，不宣称全书读取完成", async () => {
  api.mockImplementationOnce(async () => ({ data: { ...tree, events: [eventA], next_cursor: "second" } }) as never);
  api.mockImplementationOnce(async () => ({ data: { ...tree, run_id: "run-other", events: [eventB], next_cursor: null } }) as never);
  await expect(getEventTreeBook("novel-1", "task-a")).rejects.toThrow("运行身份变化");
});

it("旧过程参数不能触发过程定位或作为正式事件深链", async () => {
  renderNarrative(`${url}&process_id=process%3Aa`);
  await screen.findByLabelText("事件树画布");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.getByLabelText("事件树画布").querySelectorAll("[data-event-marker]")).toHaveLength(2);
  const sourceCalls = api.mock.calls.filter(([path]) => String(path).includes("process%3Aa/source"));
  expect(sourceCalls).toHaveLength(0);
});

it("关系直接引用正式事件，打开事件卡后原文使用事件本身的证据", async () => {
  api.mockImplementation(async (url, config) => {
    const response = narrativeResponse(String(url), new URLSearchParams(Object.entries(config?.params ?? {}).map(([key, value]) => [key, String(value)])));
    if (String(url).endsWith("event%3Aa")) (response.data as { relations: unknown[] }).relations = [{ source_kind: "event", source_id: eventA.event_id, target_kind: "event", target_id: childEvent.event_id, relation_type: "causal", reason: "关系依据", evidence: [{ chapter_id: 3, paragraph_id: 3 }], locator: { target_kind: "event", target_id: childEvent.event_id, top_level_event_id: eventA.event_id, ancestor_event_ids: [eventA.event_id], evidence_position: 1, title: childEvent.title } }];
    return { data: response.data, status: response.status } as never;
  });
  renderNarrative(url);
  await userEvent.click(await screen.findByRole("button", { name: eventA.title }));
  await screen.findByRole("dialog", { name: `事件详情：${eventA.title}` });
  await userEvent.click(screen.getByRole("button", { name: "结构目录" }));
  await userEvent.click(within(screen.getByLabelText("结构目录")).getByRole("button", { name: new RegExp(childEvent.title) }));
  const child = await screen.findByRole("dialog", { name: `事件详情：${childEvent.title}` });
  await userEvent.click(within(child).getByRole("button", { name: /原文/ }));
  const reader = await screen.findByRole("dialog", { name: "章节原文" });
  await waitFor(() => expect(reader).toHaveTextContent("原文 1"));
  expect(api.mock.calls.filter(([path]) => String(path).includes("child%3Aa/source")).some(([, config]) => config!.params.kind === "event")).toBe(true);
});
