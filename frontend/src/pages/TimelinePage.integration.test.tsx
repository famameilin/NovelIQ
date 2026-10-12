import type { ReactNode } from "react";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { installNarrativeApi, renderNarrative } from "@/test/narrativeFixtures";

vi.mock("@/components/layout/AnalysisWorkspace", () => ({ AnalysisWorkspace: ({ children }: { children: ReactNode }) => <main>{children}</main> }));
beforeEach(() => installNarrativeApi());
afterEach(() => vi.restoreAllMocks());

it("两页选择、搜索、截点、详情和原文独立恢复", async () => {
  const { router } = renderNarrative();
  await userEvent.selectOptions(await screen.findByRole("combobox", { name: "阅读截点" }), "2");
  await userEvent.click(await screen.findByRole("button", { name: /信件线索 2/ }));
  await userEvent.click(screen.getByRole("button", { name: "阅读原文" }));
  await screen.findByRole("dialog", { name: "章节原文" });
  const before = localStorage.getItem("novel-1:run-a:timeline");
  await act(async () => { await router.navigate("/novels/novel-1/event-trees?task_id=task-a"); });
  expect(screen.queryByRole("dialog", { name: "章节原文" })).not.toBeInTheDocument();
  await userEvent.click(await screen.findByRole("button", { name: "结构目录" }));
  await userEvent.click(await within(await screen.findByLabelText("全书结构目录")).findByRole("button", { name: /调查旧信/ }));
  await userEvent.type(screen.getByRole("textbox", { name: "搜索全书事件" }), "隐藏");
  await screen.findByRole("dialog", { name: "节点详情" });
  expect(localStorage.getItem("novel-1:run-a:timeline")).toBe(before);
  const treeBefore = localStorage.getItem("novel-1:run-a:event-trees");
  await act(async () => { await router.navigate("/novels/novel-1/timeline?task_id=task-a"); });
  await waitFor(() => expect(screen.getByRole("combobox", { name: "阅读截点" })).toHaveValue("2"));
  expect(await screen.findByRole("dialog", { name: "变化详情" })).toHaveTextContent("信件线索 2");
  await screen.findByRole("dialog", { name: "章节原文" });
  expect(localStorage.getItem("novel-1:run-a:event-trees")).toBe(treeBefore);
});
