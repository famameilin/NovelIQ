import { test, expect, type Page } from "@playwright/test";
import { narrativeResponse } from "../src/mocks/narrativeData";

const novelId = "narrative-fixture", taskId = "task-a";
const url = (page: "timeline" | "event-trees") => `/novels/${novelId}/${page}?task_id=${taskId}`;

async function installFixtures(page: Page, status = "completed") {
  // 所有 API 请求均由夹具响应，验收不能落到业务服务或发起真实分析
  await page.route("**/api/**", async route => {
    const request = route.request();
    if (request.method() !== "GET") return route.abort();
    const requestUrl = new URL(request.url());
    const path = requestUrl.pathname;
    if (!path.startsWith("/api/")) return route.continue();
    const novel = { novel_id: novelId, filename: "独立叙事验收.txt", title: "独立叙事验收", status, file_size: 1500, upload_time: "2026-10-09T12:00:00" };
    const task = { novel_id: novelId, task_id: taskId, status, created_at: "2026-10-09T12:00:00", progress: status === "completed" ? 100 : 40, stage: status };
    let data: unknown = {};
    if (/\/(timeline|event-trees)(\/|$)/.test(path)) {
      if (status !== "completed") return route.fulfill({ status: 400, json: { detail: `分析未完成，当前状态: ${status}`, error_type: "AnalysisNotCompleteError", status_code: 400, run_status: status } });
      const result = narrativeResponse(path, requestUrl.searchParams);
      return route.fulfill({ status: result.status, json: result.data });
    }
    if (path.endsWith("/tasks")) data = { novel_id: novelId, tasks: [task] };
    else if (path.endsWith("/status")) data = task;
    else if (path.endsWith(`/${novelId}`)) data = novel;
    else if (/\/novels\/?$/.test(path)) data = { items: [novel], total: 1, page: 1, page_size: 12, total_pages: 1 };
    return route.fulfill({ json: data });
  });
}

for (const viewport of [{ width: 1440, height: 900 }, { width: 1280, height: 720 }]) {
  test(`两页独立交互与布局 ${viewport.width}x${viewport.height}`, async ({ page }, testInfo) => {
    await page.setViewportSize(viewport);
    await installFixtures(page);
    const errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.goto(url("timeline"));
    await expect(page.getByRole("combobox", { name: "阅读截点" })).toHaveValue("1");
    await page.getByRole("combobox", { name: "阅读截点" }).selectOption("2");
    await page.getByRole("button", { name: /信件线索 2/ }).click();
    await expect(page.getByRole("dialog", { name: "变化详情" })).toContainText("信件线索 2");
    await page.getByRole("button", { name: "阅读原文", exact: true }).click();
    const reader = page.getByRole("dialog", { name: "章节原文" });
    await expect(reader).toContainText("1 / 3");
    await reader.getByRole("button", { name: "下一页原文" }).click();
    await expect(reader).toContainText("2 / 3");
    await reader.getByRole("button", { name: "关闭原文", exact: true }).click();
    await page.getByRole("button", { name: "关闭变化详情" }).click();
    await page.screenshot({ path: testInfo.outputPath("timeline.png") });
    const timelineState = await page.evaluate(key => localStorage.getItem(key), `${novelId}:run-a:timeline`);
    await page.goto(url("event-trees"));
    await expect(page.getByRole("region", { name: "全书事件树" })).toBeVisible();
    const canvas = page.getByLabel("事件树画布");
    await expect(canvas.locator("article")).toHaveCount(4);
    expect(await canvas.evaluate(element => {
      for (let parent: HTMLElement | null = element as HTMLElement; parent; parent = parent.parentElement) {
        if (/auto|scroll/.test(getComputedStyle(parent).overflowY) && parent.scrollHeight > parent.clientHeight + 1) return false;
      }
      return true;
    })).toBe(true);
    const frame = (await canvas.boundingBox())!;
    const beforeWheel = await page.evaluate(key => JSON.parse(localStorage.getItem(key)!).scale, `${novelId}:run-a:event-trees`);
    await page.mouse.move(frame.x + frame.width * .4, frame.y + frame.height * .4);
    await page.mouse.wheel(0, -120);
    await expect.poll(() => page.evaluate(key => JSON.parse(localStorage.getItem(key)!).scale, `${novelId}:run-a:event-trees`)).toBeGreaterThan(beforeWheel);
    await expect(canvas.locator("article")).toHaveCount(4);
    await page.getByRole("textbox", { name: "搜索全书事件" }).fill("隐藏");
    await page.getByLabel("全书结构目录").getByRole("button", { name: "隐藏的末页事件", exact: true }).click();
    await expect(page.getByRole("dialog", { name: "节点详情" })).toContainText("隐藏的末页事件");
    await page.getByRole("button", { name: "关闭节点详情" }).click();
    await page.getByRole("button", { name: "适应全图" }).click();
    await page.screenshot({ path: testInfo.outputPath("event-trees.png") });
    expect(await page.evaluate(key => localStorage.getItem(key), `${novelId}:run-a:timeline`)).toBe(timelineState);
    const treeState = await page.evaluate(key => localStorage.getItem(key), `${novelId}:run-a:event-trees`);
    await page.goto(url("timeline"));
    await expect(page.getByRole("combobox", { name: "阅读截点" })).toHaveValue("2");
    expect(await page.evaluate(key => localStorage.getItem(key), `${novelId}:run-a:event-trees`)).toBe(treeState);
    await expect(page.getByRole("button", { name: /逐章播放|暂停播放/ })).toHaveCount(0);
    await page.getByRole("button", { name: "下一章", exact: true }).click();
    await expect(page.getByRole("combobox", { name: "阅读截点" })).toHaveValue("3");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    expect(errors).toEqual([]);
  });
}

test("默认展开包含后页全部事件，重新进入保持选中", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await installFixtures(page);
  await page.goto(url("event-trees"));
  await expect(page.getByLabel("事件树画布").getByRole("button", { name: "调查旧信", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: /收起分支|全部展开|^折叠 |^展开 / })).toHaveCount(0);
  await page.getByRole("button", { name: "适应全图" }).click();
  await page.getByLabel("事件树画布").getByRole("button", { name: "隐藏的末页事件", exact: true }).click();
  await page.reload();
  await expect(page.getByRole("dialog", { name: "节点详情" })).toContainText("隐藏的末页事件");
});

test("取消任务两页均遵守完成读取规则", async ({ page }) => {
  await installFixtures(page, "cancelled");
  for (const view of ["timeline", "event-trees"] as const) {
    await page.goto(url(view));
    await expect(page.getByText("任务完成后才能查看结果。")).toBeVisible();
    await expect(page.getByRole("region", { name: view === "timeline" ? "连续叙事时间轴" : "全书事件树" })).toHaveCount(0);
  }
});
