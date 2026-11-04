import { buildScaleBook, scaleEventTreeResponse } from "../src/mocks/eventTreeScale";
import { test, expect, type Page } from "@playwright/test";
import { grandchildEvent, tree, narrativeResponse } from "../src/mocks/narrativeData";

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

async function installBook(page: Page, book: ReturnType<typeof buildScaleBook>) {
  await page.route(`**/api/novels/${novelId}/event-trees?*`, route => route.fulfill({ json: book }));
  await page.route(`**/api/novels/${novelId}/event-trees/nodes/**`, route => {
    const address = new URL(route.request().url());
    const response = scaleEventTreeResponse(book, address.pathname, address.searchParams);
    return route.fulfill({ status: response.status, json: response.data });
  });
}

/** 增加一个只落在浅色事件带里的深层事件，用来验证全部事件层级 */
async function installExtraEventBook(page: Page) {
  const extra = { ...grandchildEvent, event_id: "grandchild:extra", title: "补录邮戳", from: 2, to: 2, chapter_id: 2, chapter_order: 2, first_text_position: 20 };
  const book = {
    ...tree,
    events: [...tree.events, extra],
    queues: tree.queues.map((queue, index) => index === 0 ? { ...queue, event_ids: [...queue.event_ids, extra.event_id] } : queue),
    counts: { ...tree.counts, all_events: tree.counts.all_events + 1 },
  };
  await installBook(page, book);
}

for (const viewport of [{ width: 1440, height: 900 }, { width: 1280, height: 720 }]) {
  test(`事件线展示、节点详情、目录与独立时间轴状态 ${viewport.width}x${viewport.height}`, async ({ page }, testInfo) => {
    await page.setViewportSize(viewport);
    await installFixtures(page);
    await installExtraEventBook(page);
    const errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.goto(url("timeline"));
    await page.getByRole("combobox", { name: "阅读截点" }).selectOption("2");
    const timelineState = await page.evaluate(key => localStorage.getItem(key), `${novelId}:run-a:timeline`);
    await page.goto(url("event-trees"));
    const canvas = page.getByLabel("事件线画布");
    await expect(page.getByLabel("事件线数")).toContainText("2");
    await expect(page.getByLabel("事件数")).toContainText("5");
    await expect(canvas.locator("[data-line-header]")).toHaveCount(2);
    await expect(canvas.locator('[data-line-node="event:a"]')).toBeVisible();
    await expect(canvas.locator('[data-line-node="event:b"]')).toBeVisible();
    await canvas.getByRole("button", { name: "最初的信", exact: true }).click();
    const detail = page.getByLabel("事件详情");
    await expect(detail).toContainText("调查者找到最初的信");
    await expect(detail).toContainText("所在叙事线");
    await expect(detail.getByRole("button", { name: /辨认信封印记/ })).toBeVisible();
    await detail.getByRole("button", { name: /查看完整内容/ }).click();
    const reader = page.getByRole("dialog", { name: "章节原文" });
    await expect(reader).toContainText("原文 1");
    await reader.getByRole("button", { name: "关闭原文" }).click();
    await expect(detail).toContainText("所属事件");
    await page.getByLabel("视图样式").selectOption("directory");
    const directory = page.getByLabel("事件目录");
    await expect(directory).toBeVisible();
    await directory.getByRole("button", { name: /隐藏的末页事件/ }).click();
    await expect(page.getByLabel("事件详情")).toContainText("隐藏的末页事件");
    const frame = (await page.locator("[aria-label='全书事件树']").boundingBox())!;
    await page.screenshot({ path: testInfo.outputPath("event-lines.png"), clip: frame, animations: "disabled" });
    expect(await page.evaluate(key => localStorage.getItem(key), `${novelId}:run-a:timeline`)).toBe(timelineState);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    expect(errors).toEqual([]);
  });
}

for (const viewport of [{ width: 1440, height: 900 }, { width: 1280, height: 720 }]) {
  test(`子事件深链补入事件线并保持选中 ${viewport.width}x${viewport.height}`, async ({ page }, testInfo) => {
    await page.setViewportSize(viewport);
    await installFixtures(page);
    await page.goto(`${url("event-trees")}&event_id=grandchild%3Aa`);
    const canvas = page.getByLabel("事件线画布");
    await expect(page.getByLabel("事件详情")).toContainText("核对邮戳");
    await expect(canvas.locator('[data-line-node="grandchild:a"]')).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await page.getByRole("button", { name: "切换深浅模式" }).click();
    await expect(page.locator("html")).toHaveClass(/\bdark\b/);
    await page.screenshot({ path: testInfo.outputPath("event-lines-dark.png"), animations: "disabled" });
    await page.getByRole("button", { name: "切换深浅模式" }).click();
    await expect(page.locator("html")).not.toHaveClass(/\bdark\b/);
    await expect(canvas.locator('[data-line-node="grandchild:a"]')).toHaveAttribute("aria-pressed", "true");
  });
}

test("取消任务两页均遵守完成读取规则", async ({ page }) => {
  await installFixtures(page, "cancelled");
  for (const view of ["timeline", "event-trees"] as const) {
    await page.goto(url(view));
    await expect(page.getByText("任务完成后才能查看结果。")).toBeVisible();
    await expect(page.getByRole("region", { name: view === "timeline" ? "连续叙事时间轴" : "全书事件树" })).toHaveCount(0);
  }
});

for (const { scale, width, height } of [
  { scale: 30, width: 1672, height: 941 },
  { scale: 30, width: 1440, height: 900 },
  { scale: 30, width: 1280, height: 720 },
  { scale: 100, width: 1672, height: 941 },
  { scale: 300, width: 1672, height: 941 },
]) {
  test(`${scale}章结构夹具按正式事件线入口展示并可平移定位 ${width}x${height}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height });
    await installFixtures(page);
    const book = buildScaleBook({ chapters: scale, eventsPerChapter: 4, trees: scale === 30 ? 7 : 16, outcomes: scale === 30 ? 9 : 18 });
    book.run_id = "run-a";
    await installBook(page, book);
    await page.goto(url("event-trees"));
    const canvas = page.getByLabel("事件线画布");
    const lineCount = Number(await page.getByLabel("事件线数").locator("strong").textContent());
    expect(lineCount).toBe(book.event_line_ids.length);
    expect(lineCount).toBeGreaterThanOrEqual(5);
    await expect(canvas.locator("[data-line-header]")).toHaveCount(lineCount);
    await expect(page.getByLabel("事件数")).toContainText(String(book.events.length));
    await expect(canvas.locator("[data-line-book]")).toContainText(String(book.events.length));
    const titles = await canvas.locator("[data-line-header]").evaluateAll(nodes => nodes.map(node => node.textContent ?? ""));
    expect(new Set(titles).size).toBe(titles.length);
    const frame = (await canvas.boundingBox())!;
    const content = canvas.locator(":scope > div");
    const transform = () => content.evaluate(element => {
      const match = (element as HTMLElement).style.transform.match(/translate\((-?[\d.]+)px,\s*(-?[\d.]+)px\)/);
      return { x: Number(match?.[1] ?? 0), y: Number(match?.[2] ?? 0) };
    });
    const before = await transform();
    await page.mouse.move(frame.x + frame.width - 24, frame.y + frame.height * 0.5);
    await page.mouse.down();
    await page.mouse.move(frame.x + frame.width * 0.2, frame.y + frame.height * 0.45);
    await page.mouse.up();
    await expect.poll(async () => (await transform()).x).not.toBe(before.x);
    const contentWidth = await content.evaluate(element => (element as HTMLElement).offsetWidth);
    const panned = await transform();
    expect(panned.x).toBeGreaterThanOrEqual(Math.min(0, frame.width - contentWidth));
    expect(panned.x).toBeLessThanOrEqual(0);
    await page.getByRole("button", { name: "适应画布" }).click();
    const node = canvas.locator("[data-line-node]").first();
    const title = (await node.getAttribute("aria-label"))!;
    await node.click();
    await expect(page.getByLabel("事件详情")).toContainText(title);
    await page.getByLabel("视图样式").selectOption("directory");
    const directory = page.getByLabel("事件目录");
    const lastChapter = scale;
    await directory.getByRole("button", { name: new RegExp(`第 ${lastChapter} 章事件 3`) }).click();
    await expect(page.getByLabel("事件详情")).toContainText(`第 ${lastChapter} 章事件 3`);
    await page.screenshot({ path: testInfo.outputPath(`event-lines-${scale}-chapters.png`), animations: "disabled" });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}

test("旧过程参数不触发详情或原文请求", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await installFixtures(page);
  const detailRequests: string[] = [];
  page.on("request", request => {
    if (new URL(request.url()).pathname.includes("/event-trees/nodes/")) detailRequests.push(request.url());
  });
  await page.goto(`${url("event-trees")}&process_id=process%3Aa`);
  await expect(page.getByLabel("事件线画布")).toBeVisible();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(detailRequests.filter(request => request.includes("process"))).toEqual([]);
});

test("诊断报告前显示已保存事件线及独立章节范围", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await installFixtures(page);
  await page.route(`**/api/novels/${novelId}/event-trees?*`, route => route.fulfill({
    json: { ...tree, organization_status: "pending_diagnosis" },
  }));
  await page.goto(url("event-trees"));
  await page.getByLabel("事件线画布").getByRole("button", { name: "最初的信", exact: true }).click();
  const detail = page.getByLabel("事件详情");
  await expect(detail).toContainText("章节范围");
  await expect(detail).toContainText("章节 1 至 章节 3");
  await detail.getByRole("button", { name: /查看完整内容/ }).click();
  await expect(page.getByRole("dialog", { name: "章节原文" })).toContainText("原文 1");
  await page.screenshot({ path: testInfo.outputPath("saved-event-lines-before-report.png"), animations: "disabled" });
});
