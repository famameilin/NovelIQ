import { buildScaleBook } from "../src/mocks/eventTreeScale";
import { test, expect, type Page } from "@playwright/test";
import { narrativeResponse } from "../src/mocks/narrativeData";
import { EVENT_TREE_CONTRACT_VERSION } from "../src/api/narrativeTypes";

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

const treeKey = `${novelId}:run-a:event-trees:${EVENT_TREE_CONTRACT_VERSION}`;
for (const viewport of [{ width: 1440, height: 900 }, { width: 1280, height: 720 }]) {
  test(`桌面事件树、卡片和独立状态 ${viewport.width}x${viewport.height}`, async ({ page }, testInfo) => {
    await page.setViewportSize(viewport);
    await installFixtures(page);
    const errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.goto(url("timeline"));
    await page.getByRole("combobox", { name: "阅读截点" }).selectOption("2");
    const timelineState = await page.evaluate(key => localStorage.getItem(key), `${novelId}:run-a:timeline`);
    await page.goto(url("event-trees"));
    const canvas = page.getByLabel("事件树画布");
    await expect(canvas.locator("[data-event-marker]")).toHaveCount(2);
    await expect(canvas.locator("[data-outcome-id]")).toHaveCount(1);
    await expect(canvas.locator("[data-arc-anchor]")).toHaveCount(1);
    await expect(page.getByRole("textbox")).toHaveCount(0);
    await expect(page.getByRole("button", { name: /搜索|缩放|适应全图|力导向/ })).toHaveCount(0);
    await expect.poll(() => canvas.evaluate(element => {
      for (let parent: HTMLElement | null = element as HTMLElement; parent; parent = parent.parentElement) {
        if (/auto|scroll/.test(getComputedStyle(parent).overflowY) && parent.scrollHeight > parent.clientHeight + 1) return { className: parent.className, scrollHeight: parent.scrollHeight, clientHeight: parent.clientHeight };
      }
      return true;
    })).toBe(true);
    const frame = (await canvas.boundingBox())!;
    const content = canvas.locator(":scope > div");
    const before = await content.evaluate(element => (element as HTMLElement).style.transform);
    await page.mouse.move(frame.x + frame.width * .6, frame.y + frame.height * .4);
    await page.mouse.wheel(100, -120);
    expect(await content.evaluate(element => (element as HTMLElement).style.transform)).toBe(before);
    await page.mouse.down();
    await page.mouse.move(frame.x + frame.width * .6 - 40, frame.y + frame.height * .4 + 80);
    await page.mouse.up();
    const contentWidth = await content.evaluate(element => (element as HTMLElement).offsetWidth);
    await expect.poll(() => page.evaluate(key => localStorage.getItem(key), treeKey)).not.toBeNull();
    expect(await page.evaluate(key => JSON.parse(localStorage.getItem(key)!).x, treeKey)).toBe(Math.max(-40, Math.min(0, frame.width - contentWidth)));
    expect(await content.evaluate(element => (element as HTMLElement).style.transform)).toMatch(/^translateX/);
    await canvas.getByRole("button", { name: "最初的信", exact: true }).click();
    const parent = page.getByRole("dialog", { name: "事件详情：最初的信" });
    await expect(parent).toBeVisible();
    await parent.getByRole("button", { name: /辨认信封印记/ }).click();
    const child = page.getByRole("dialog", { name: "事件详情：辨认信封印记" });
    await child.getByRole("button", { name: /核对邮戳/ }).click();
    await expect(page.getByRole("dialog", { name: "事件详情：核对邮戳" })).toBeVisible();
    await expect(parent).toBeVisible();
    await expect(child).toBeVisible();
    const body = parent.locator("[data-card-body]");
    expect(await body.evaluate(element => {
      const range = document.createRange(); range.selectNodeContents(element); const selection = window.getSelection()!;
      selection.removeAllRanges(); selection.addRange(range); return selection.toString();
    })).toContain("调查者找到最初的信");
    const header = parent.locator("[data-card-header]");
    const headerBox = (await header.boundingBox())!, cardBefore = (await parent.boundingBox())!;
    await page.mouse.move(headerBox.x + 60, headerBox.y + 20); await page.mouse.down();
    await page.mouse.move(headerBox.x + 115, headerBox.y + 48); await page.mouse.up();
    expect((await parent.boundingBox())!.x).toBeCloseTo(cardBefore.x + 55, 0);
    expect((await parent.boundingBox())!.y).toBeCloseTo(cardBefore.y + 28, 0);
    await page.screenshot({ path: testInfo.outputPath("event-trees.png") });
    await child.getByRole("button", { name: "关闭事件卡" }).click();
    await expect(parent).toBeVisible();
    await page.getByRole("dialog", { name: "事件详情：核对邮戳" }).getByRole("button", { name: "关闭事件卡" }).click();
    await parent.getByRole("button", { name: "阅读原文" }).click();
    const reader = page.getByRole("dialog", { name: "章节原文" });
    await expect(reader).toContainText("原文 1");
    await reader.getByRole("button", { name: "下一页原文" }).click();
    await reader.getByRole("button", { name: "关闭原文" }).click();
    expect(await page.evaluate(key => localStorage.getItem(key), `${novelId}:run-a:timeline`)).toBe(timelineState);
    await page.reload();
    await expect(page.getByRole("dialog", { name: "事件详情：最初的信" })).toBeVisible();
    const state = await page.evaluate(key => localStorage.getItem(key), treeKey);
    expect(state).not.toBeNull();
    await page.goto(url("timeline"));
    await expect(page.getByRole("combobox", { name: "阅读截点" })).toHaveValue("2");
    expect(await page.evaluate(key => localStorage.getItem(key), treeKey)).toBe(state);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    expect(errors).toEqual([]);
  });
}

for (const viewport of [{ width: 1440, height: 900 }, { width: 1280, height: 720 }]) {
  test(`子事件深链保持唯一大事件入口，真实明暗及小说主题切换 ${viewport.width}x${viewport.height}`, async ({ page }, testInfo) => {
    await page.setViewportSize(viewport);
    await installFixtures(page);
    // 主题色经正式诊断读取链进入页面，不直接改写根节点的样式或明暗类名
    let themeColor = "#E84393";
    await page.route(`**/api/novels/${novelId}/diagnosis?*`, route => route.fulfill({ json: { theme_color: themeColor } }));
    await page.goto(`${url("event-trees")}&event_id=grandchild%3Aa`);
    const canvas = page.getByLabel("事件树画布");
    const cards = page.locator("[data-event-card]");
    const dot = canvas.locator("[data-event-dot]").first();
    const backgroundBrightness = () => canvas.evaluate(element => {
      const background = getComputedStyle(element.closest(".bg-background")!).backgroundColor;
      const channels = background.match(/[\d.]+/g)!.slice(0, 3).map(Number);
      return channels.reduce((sum, value) => sum + value, 0) / 3;
    });
    const stableScreenshot = async (name: string) => {
      // 页面进入动画完成后再截图，避免把过渡帧误当作主题的实际颜色
      await expect.poll(() => canvas.evaluate(element => {
        for (let parent: HTMLElement | null = element as HTMLElement; parent; parent = parent.parentElement) {
          if (Number(getComputedStyle(parent).opacity) < 1) return false;
        }
        return true;
      })).toBe(true);
      await page.screenshot({ path: testInfo.outputPath(name), animations: "disabled" });
    };
    await expect(page.getByRole("dialog", { name: "事件详情：核对邮戳" })).toBeVisible();
    await expect(cards).toHaveCount(3);
    await expect(canvas.locator("[data-event-marker]")).toHaveCount(2);
    await expect.poll(() => page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue("--chart-1").trim())).toMatch(/^331\s/);
    await expect.poll(backgroundBrightness).toBeGreaterThan(180);
    const lightDot = await dot.evaluate(element => getComputedStyle(element).backgroundColor);
    const lightCard = await cards.first().evaluate(element => getComputedStyle(element).backgroundColor);
    await stableScreenshot("event-trees-light.png");

    await page.getByRole("button", { name: "切换深浅模式" }).click();
    await expect(page.locator("html")).toHaveClass(/\bdark\b/);
    await expect.poll(backgroundBrightness).toBeLessThan(80);
    await expect.poll(() => dot.evaluate(element => getComputedStyle(element).backgroundColor)).not.toBe(lightDot);
    await expect.poll(() => cards.first().evaluate(element => getComputedStyle(element).backgroundColor)).not.toBe(lightCard);
    await stableScreenshot("event-trees-dark.png");

    await page.reload();
    await expect(cards).toHaveCount(3);
    await expect(page.locator("html")).toHaveClass(/\bdark\b/);
    await expect.poll(() => page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue("--chart-1").trim())).toMatch(/^331\s/);
    await expect.poll(backgroundBrightness).toBeLessThan(80);
    const darkDot = await dot.evaluate(element => getComputedStyle(element).backgroundColor);
    themeColor = "#2F9E44";
    await page.reload();
    await expect(cards).toHaveCount(3);
    await expect.poll(() => page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue("--chart-1").trim())).toMatch(/^131\s/);
    await expect.poll(() => dot.evaluate(element => getComputedStyle(element).backgroundColor)).not.toBe(darkDot);
    await expect.poll(backgroundBrightness).toBeLessThan(80);
    await stableScreenshot("event-trees-novel-theme-dark.png");

    await page.getByRole("button", { name: "切换深浅模式" }).click();
    await expect(page.locator("html")).not.toHaveClass(/\bdark\b/);
    await expect.poll(backgroundBrightness).toBeGreaterThan(180);
    await expect(cards).toHaveCount(3);
    await expect(canvas.locator("[data-event-marker]")).toHaveCount(2);
    await stableScreenshot("event-trees-light-restored.png");
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
  test(`${scale}章结构夹具横向定位完整事件、结果及叙事线 ${width}x${height}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height });
    await installFixtures(page);
    const book = buildScaleBook({ chapters: scale, eventsPerChapter: 4, arcs: scale === 30 ? 7 : 16, outcomes: scale === 30 ? 9 : 18 });
    book.run_id = "run-a";
    await page.route(`**/api/novels/${novelId}/event-trees?*`, route => route.fulfill({ json: book }));
    await page.route(`**/api/novels/${novelId}/event-trees/nodes/*`, route => {
      const eventId = decodeURIComponent(new URL(route.request().url()).pathname.split("/").at(-1)!);
      const event = book.events.find(item => item.event_id === eventId)!;
      // 详情与画布使用同一组正式关联，不能让卡片夹具虚报无关联叙事线
      const arcs = book.event_arc_links.filter(link => link.event_id === eventId).map(link => {
        const arc = book.arcs.find(item => item.arc_id === link.arc_id)!;
        return { arc_id: arc.arc_id, title: arc.title, kind: arc.kind, role: link.role, reason: link.reason };
      });
      return route.fulfill({ json: { kind: "event", ...event, run_id: book.run_id, progress: 0.5, arcs, characters: [], direct_children: [], evidence: [], evidence_scope: "paragraph", source_chapters: [], ancestry: [], revision_id: `revision:${eventId}`, relations: [] } });
    });
    await page.goto(url("event-trees"));
    const canvas = page.getByLabel("事件树画布");
    await expect(page.getByText(`全书 · ${scale * 4} 个大事件`, { exact: false })).toBeVisible();
    await expect(canvas.locator("[data-arc-anchor]")).toHaveCount(book.arcs.length);
    expect(await canvas.locator("[data-event-marker]").count()).toBeLessThanOrEqual(book.events.length);
    // 等待页面进入动画完成，初始构图与选中构图都采用稳态画面
    await expect.poll(() => canvas.evaluate(element => {
      for (let parent: HTMLElement | null = element as HTMLElement; parent; parent = parent.parentElement) {
        if (Number(getComputedStyle(parent).opacity) < 1) return false;
      }
      return true;
    })).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`event-tree-${scale}-initial.png`) });
    if (scale > 30) {
      const frame = (await canvas.boundingBox())!;
      const anchorBefore = (await canvas.locator("[data-arc-dot]").first().boundingBox())!;
      // 从锚点说明下方留白起拖，密集长篇场景不能误按真实事件按钮
      await page.mouse.move(frame.x + frame.width * .6, frame.y + frame.height - 8);
      await page.mouse.down();
      await page.mouse.move(frame.x + frame.width * .6 - 60, frame.y + frame.height - 88);
      await page.mouse.up();
      const anchorAfter = (await canvas.locator("[data-arc-dot]").first().boundingBox())!;
      expect(anchorAfter.x).toBeCloseTo(anchorBefore.x - 60, 1);
      expect(anchorAfter.y).toBeCloseTo(anchorBefore.y, 1);
    }
    if (width === 1672 && scale === 30) {
      expect(await canvas.locator("[data-event-marker]").count()).toBe(120);
      const frame = (await canvas.boundingBox())!;
      for (const anchor of await canvas.locator("[data-arc-dot]").all()) {
        const bounds = (await anchor.boundingBox())!;
        expect(bounds.y + bounds.height / 2).toBeCloseTo(792, 0);
      }
      for (const box of await canvas.locator("[data-outcome-id]").all()) {
        const bounds = (await box.boundingBox())!;
        expect(bounds.x).toBeGreaterThanOrEqual(frame.x);
        expect(bounds.x + bounds.width).toBeLessThanOrEqual(frame.x + frame.width);
      }
    }
    await page.getByRole("button", { name: "结构目录" }).click();
    await expect(page.getByLabel("结构目录").getByRole("button", { name: `第 ${scale} 章事件 3`, exact: true })).toBeVisible();
    await page.getByLabel("结构目录").getByRole("button", { name: `第 ${scale} 章事件 3`, exact: true }).click();
    await expect(canvas.getByRole("button", { name: `第 ${scale} 章事件 3`, exact: true })).toBeVisible();
    expect(await canvas.locator("[data-event-marker]").count()).toBeLessThanOrEqual(book.events.length);
    const transform = await canvas.locator(":scope > div").evaluate(element => (element as HTMLElement).style.transform);
    expect(transform).toMatch(/^translateX/);
    const selectedId = `ev-${scale}-3`;
    const selectedCard = page.getByRole("dialog", { name: `事件详情：第 ${scale} 章事件 3` });
    for (const link of book.event_arc_links.filter(item => item.event_id === selectedId)) {
      await expect(selectedCard).toContainText(book.arcs.find(arc => arc.arc_id === link.arc_id)!.title);
    }
    await expect(selectedCard).not.toContainText("无关联叙事线");
    const selectedDot = (await canvas.locator(`[data-event-marker="${selectedId}"] [data-event-dot]`).boundingBox())!;
    const arcPath = canvas.locator(`path[data-channel="arc"][data-target-id="${selectedId}"]`).first();
    const sourceId = await arcPath.getAttribute("data-source-id");
    const arcDot = (await canvas.locator(`[data-arc-anchor="${sourceId}"] [data-arc-dot]`).boundingBox())!;
    const coordinates = (await arcPath.getAttribute("d"))!.match(/-?\d+\.?\d*/g)!.map(Number);
    const frame = (await canvas.boundingBox())!;
    const pan = Number(transform.match(/translateX\((-?[\d.]+)px\)/)![1]);
    expect(frame.x + pan + coordinates[0]).toBeCloseTo(arcDot.x + arcDot.width / 2, 1);
    expect(frame.y + coordinates[1]).toBeCloseTo(arcDot.y + arcDot.height / 2, 1);
    expect(frame.x + pan + coordinates[6]).toBeCloseTo(selectedDot.x + selectedDot.width / 2, 1);
    expect(frame.y + coordinates[7]).toBeCloseTo(selectedDot.y + selectedDot.height / 2 + 6, 1);
    const outcomePath = canvas.locator(`path[data-channel="outcome"][data-source-id="${selectedId}"]`).first();
    const outcomeCoordinates = (await outcomePath.getAttribute("d"))!.match(/-?\d+\.?\d*/g)!.map(Number);
    expect(frame.x + pan + outcomeCoordinates[0]).toBeCloseTo(selectedDot.x + selectedDot.width / 2, 1);
    expect(frame.y + outcomeCoordinates[1]).toBeCloseTo(selectedDot.y + selectedDot.height / 2 - 6, 1);
    await page.screenshot({ path: testInfo.outputPath(`event-tree-${scale}-chapters.png`) });
  });
}

test("旧过程参数不触发事件定位、开卡或原文请求", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await installFixtures(page);
  const detailRequests: string[] = [];
  // 旧过程身份不能被映射成正式事件，也不能触发事件详情或原文读取
  page.on("request", request => {
    if (new URL(request.url()).pathname.includes("/event-trees/nodes/")) detailRequests.push(request.url());
  });
  await page.goto(`${url("event-trees")}&process_id=process%3Aa`);
  await expect(page.getByLabel("事件树画布").locator("[data-event-marker]")).toHaveCount(2);
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.locator("[data-event-card]")).toHaveCount(0);
  await expect(page.locator("[data-event-marker][data-selected]")).toHaveCount(0);
  expect(detailRequests).toEqual([]);
});
