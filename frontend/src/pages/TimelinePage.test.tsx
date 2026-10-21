import type { ReactNode } from "react";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { installNarrativeApi, renderNarrative } from "@/test/narrativeFixtures";

vi.mock("@/components/layout/AnalysisWorkspace", () => ({ AnalysisWorkspace: ({ children }: { children: ReactNode }) => <main>{children}</main> }));
let api: ReturnType<typeof installNarrativeApi>;
beforeEach(() => { api = installNarrativeApi(); });
afterEach(() => vi.restoreAllMocks());

it("首次从首章开始，全书变化直接可见，筛选保持章节坐标", async () => {
  renderNarrative();
  const cutoff = await screen.findByRole("combobox", { name: "阅读截点" });
  expect(cutoff).toHaveValue("1");
  await screen.findByText("信件线索 3");
  const coordinates = screen.getAllByRole("button", { name: /^阅读至第 \d+ 章$/ }).map(node => node.style.left);
  await userEvent.type(screen.getByRole("textbox", { name: "搜索全部变化" }), "线索 3");
  await waitFor(() => expect(within(screen.getByLabelText("变化清单")).getAllByRole("button")).toHaveLength(1));
  expect(screen.getAllByRole("button", { name: /^阅读至第 \d+ 章$/ }).map(node => node.style.left)).toEqual(coordinates);
  await userEvent.selectOptions(cutoff, "3");
  expect(JSON.parse(localStorage.getItem("novel-1:run-a:timeline")!).cutoff).toBe(3);
});

it("图谱事实入口避开旧筛选，退出映射保留入口截点", async () => {
  localStorage.setItem("novel-1:run-a:timeline", JSON.stringify({ cutoff: 1, q: "旧筛选", dimension: "character", window: 8 }));
  renderNarrative("/novels/novel-1/timeline?task_id=task-a&through_chapter_id=3&source_fact_id=fact-3");
  await waitFor(() => expect(screen.getByRole("dialog", { name: "变化详情" })).toHaveTextContent("信件线索 3"));
  expect(api.mock.calls.some(([, config]) => {
    const params = (config as { params?: Record<string, unknown> } | undefined)?.params ?? {};
    return params.source_fact_id === "fact-3" && params.q === "" && params.dimension === undefined && params.window_start_chapter_id === undefined;
  })).toBe(true);
  await userEvent.click(screen.getByRole("button", { name: "显示全部变化" }));
  expect(screen.getByRole("combobox", { name: "阅读截点" })).toHaveValue("3");
  expect(JSON.parse(localStorage.getItem("novel-1:run-a:timeline")!).cutoff).toBe(3);
});

it("仅章节入口同样定位，长段原文关闭重开保留分片位置", async () => {
  renderNarrative("/novels/novel-1/timeline?task_id=task-a&through_chapter_id=2");
  expect(await screen.findByRole("combobox", { name: "阅读截点" })).toHaveValue("2");
  await userEvent.click(await screen.findByRole("button", { name: /信件线索 2/ }));
  await userEvent.click(screen.getByRole("button", { name: "阅读原文" }));
  const reader = await screen.findByRole("dialog", { name: "章节原文" });
  await waitFor(() => expect(reader).toHaveTextContent("1 / 3"));
  await userEvent.click(within(reader).getByRole("button", { name: "下一页原文" }));
  expect(reader).toHaveTextContent("2 / 3");
  await userEvent.click(within(reader).getByRole("button", { name: "关闭原文" }));
  await userEvent.click(screen.getByRole("button", { name: "阅读原文" }));
  await waitFor(() => expect(screen.getByRole("dialog", { name: "章节原文" })).toHaveTextContent("2 / 3"));
});

it("未完成任务只显示项目统一等待状态", async () => {
  api.mockRejectedValue({ isAxiosError: true, response: { status: 400, data: { error_type: "AnalysisNotCompleteError", run_status: "running" } } });
  renderNarrative();
  await screen.findByText("任务完成后才能查看结果。");
  expect(screen.queryByRole("combobox", { name: "阅读截点" })).not.toBeInTheDocument();
});
