import { test, expect } from "@playwright/test";
import { buildScaleBook, scaleEventTreeResponse } from "../src/mocks/eventTreeScale";

const sparseBook = buildScaleBook({ chapters: 26, eventsPerChapter: 6, trees: 8, outcomes: 8 });
const rootA = sparseBook.event_line_ids[0];
const rootB = sparseBook.event_line_ids[1];
const rootEvent = sparseBook.events.find(event => event.event_id === rootA)!;
sparseBook.relations = [{
  relation_id: "root-link", source_kind: "event", source_id: rootA, target_kind: "event", target_id: rootB,
  relation_type: "reference", reason: "两棵事件树引用同一批档案线索", evidence: [{ chapter_id: rootEvent.chapter_id, paragraph_id: rootEvent.chapter_id }],
}];
sparseBook.counts.relations = sparseBook.relations.length;
const novelId = "event-tree-sparse-fixture";

for (const viewport of [{ width: 1874, height: 875 }, { width: 1280, height: 720 }]) {
  test(`稀疏长篇归并为五到十条事件线并可平移、查看详情 ${viewport.width}x${viewport.height}`, async ({ page }, testInfo) => {
    await page.setViewportSize(viewport);
    const errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.route("**/api/**", async route => {
      if (route.request().method() !== "GET") return route.abort();
      const address = new URL(route.request().url());
      const path = address.pathname;
      if (!path.startsWith("/api/")) return route.continue();
      if (path.includes("/event-trees/nodes/")) {
        const response = scaleEventTreeResponse(sparseBook, path, address.searchParams);
        return route.fulfill({ status: response.status, json: response.data });
      }
      let data: unknown = {};
      const novel = { novel_id: novelId, title: "稀疏关联验收", filename: "稀疏关联验收.txt", status: "completed", file_size: 1500, upload_time: "2026-10-19T00:00:00" };
      const task = { task_id: sparseBook.run_id, novel_id: novelId, status: "completed", progress: 100, created_at: "2026-10-19T00:00:00" };
      if (path.endsWith("/event-trees")) data = sparseBook;
      else if (path.endsWith("/tasks")) data = { novel_id: novelId, tasks: [task] };
      else if (path.endsWith("/status")) data = task;
      else if (path.endsWith(`/${novelId}`)) data = novel;
      else if (/\/novels\/?$/.test(path)) data = { items: [novel], total: 1, page: 1, page_size: 12, total_pages: 1 };
      return route.fulfill({ json: data });
    });
    await page.goto(`/novels/${novelId}/event-trees?task_id=${sparseBook.run_id}`);
    const canvas = page.getByLabel("事件线画布");
    const lineCount = Number(await page.getByLabel("事件线数").locator("strong").textContent());
    expect(lineCount).toBeGreaterThanOrEqual(5);
    expect(lineCount).toBeLessThanOrEqual(10);
    await expect(canvas.locator("[data-line-header]")).toHaveCount(lineCount);
    await expect(page.getByLabel("事件数")).toContainText(String(sparseBook.events.length));
    const titles = await canvas.locator("[data-line-header]").evaluateAll(nodes => nodes.map(node => node.textContent ?? ""));
    expect(new Set(titles).size).toBe(titles.length);
    const frame = (await canvas.boundingBox())!;
    const content = canvas.locator(":scope > div");
    const contentWidth = await content.evaluate(element => (element as HTMLElement).offsetWidth);
    expect(contentWidth).toBeGreaterThanOrEqual(1170);
    const transform = () => content.evaluate(element => {
      const match = (element as HTMLElement).style.transform.match(/translate\((-?[\d.]+)px,\s*(-?[\d.]+)px\)/);
      return { x: Number(match?.[1] ?? 0), y: Number(match?.[2] ?? 0) };
    });
    const before = await transform();
    await page.mouse.move(frame.x + frame.width - 24, frame.y + frame.height * 0.5);
    await page.mouse.down();
    await page.mouse.move(frame.x + frame.width * 0.2, frame.y + frame.height * 0.45);
    await page.mouse.up();
    if (contentWidth > frame.width) {
      await expect.poll(async () => (await transform()).x).not.toBe(before.x);
      const panned = await transform();
      expect(panned.x).toBeGreaterThanOrEqual(Math.min(0, frame.width - contentWidth));
      expect(panned.x).toBeLessThanOrEqual(0);
    } else {
      expect((await transform()).x).toBe(before.x);
    }
    await page.getByRole("button", { name: "放大" }).click();
    await page.getByRole("button", { name: "放大" }).click();
    await expect(page.getByText("120%", { exact: true })).toBeVisible();
    const beforeVertical = await transform();
    await page.mouse.move(frame.x + frame.width * 0.5, frame.y + frame.height * 0.75);
    await page.mouse.down();
    await page.mouse.move(frame.x + frame.width * 0.5, frame.y + frame.height * 0.25);
    await page.mouse.up();
    const afterVertical = await transform();
    expect(afterVertical.y).toBeLessThan(beforeVertical.y);
    const contentHeight = await content.evaluate(element => (element as HTMLElement).offsetHeight);
    expect(afterVertical.y).toBeGreaterThanOrEqual(frame.height - contentHeight * 1.2 - 0.5);
    await page.getByRole("button", { name: "适应画布" }).click();
    await expect(page.getByText("100%", { exact: true })).toBeVisible();
    expect((await transform()).y).toBe(0);
    await canvas.locator("[data-line-node]").first().click();
    await expect.poll(async () => canvas.locator("[data-line-relation]").count()).toBeGreaterThan(0);
    const relationCount = await canvas.locator("[data-line-relation]").count();
    expect(relationCount).toBeGreaterThan(0);
    await page.getByRole("switch", { name: /显示关联线/ }).click();
    await expect(canvas.locator("[data-line-relation]")).toHaveCount(0);
    await page.getByRole("switch", { name: /显示关联线/ }).click();
    await expect(canvas.locator("[data-line-relation]")).toHaveCount(relationCount);
    const node = canvas.locator("[data-line-node]").first();
    const title = (await node.getAttribute("aria-label"))!;
    await node.click();
    const detail = page.getByLabel("事件详情");
    await expect(detail).toContainText(title);
    await expect(detail).toContainText("所在叙事线");
    await detail.getByRole("button", { name: /查看完整内容/ }).click();
    const reader = page.getByRole("dialog", { name: "章节原文" });
    await expect(reader).toContainText("原文");
    await reader.getByRole("button", { name: "关闭原文" }).click();
    await page.screenshot({ path: testInfo.outputPath("sparse-lines-light.png"), animations: "disabled" });
    await page.getByRole("button", { name: "切换深浅模式" }).click();
    await expect(page.locator("html")).toHaveClass(/dark/);
    await page.screenshot({ path: testInfo.outputPath("sparse-lines-dark.png"), animations: "disabled" });
    expect(errors).toEqual([]);
  });
}
