import { expect, test, type Page, type TestInfo } from "@playwright/test";

async function captureScene(page: Page, testInfo: TestInfo, referenceScene = false) {
  await page.setViewportSize({ width: 1756, height: 953 });
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.goto(referenceScene ? "/novels/event-tree-reference/event-trees?task_id=reference-scene&mock=true" : "/novels/narrative-design-demo/event-trees?task_id=narrative-design-task&mock=true");
  const canvas = page.getByLabel("事件线画布");
  await expect(canvas.locator("[data-line-header]")).toHaveCount(7);
  await expect(page.getByLabel("事件数")).toContainText(referenceScene ? "156" : "127");
  await page.evaluate(() => document.fonts.ready);
  const headers = await canvas.locator("[data-line-header]").evaluateAll(nodes => nodes.map(node => ({ text: node.textContent ?? "", top: node.getBoundingClientRect().top, bottom: node.getBoundingClientRect().bottom })));
  expect(new Set(headers.map(header => header.text)).size).toBe(headers.length);
  const frame = (await canvas.boundingBox())!;
  const contentWidth = await canvas.locator(":scope > div").evaluate(element => (element as HTMLElement).offsetWidth);
  expect(contentWidth).toBeGreaterThanOrEqual(1170);
  const visibleHeaders = headers.filter(header => header.top < frame.y + frame.height);
  expect(visibleHeaders.length).toBeGreaterThanOrEqual(6);
  for (const header of visibleHeaders) {
    expect(header.top).toBeGreaterThanOrEqual(frame.y);
    expect(header.bottom).toBeLessThanOrEqual(frame.y + frame.height);
  }
  const node = canvas.locator("[data-line-node]").first();
  const title = (await node.getAttribute("aria-label"))!;
  await node.click();
  const detail = page.getByRole("complementary", { name: "事件详情" });
  await expect(detail).toContainText(title);
  await expect(detail).toContainText("所在叙事线");
  await detail.getByRole("button", { name: /查看完整内容/ }).click();
  const reader = page.getByRole("dialog", { name: "章节原文" });
  await expect(reader).toBeVisible();
  await expect(reader).toContainText("原文");
  await reader.getByRole("button", { name: "关闭原文" }).click();
  await page.screenshot({ path: testInfo.outputPath("page-light.png"), animations: "disabled" });
  await page.screenshot({ path: testInfo.outputPath("canvas-light.png"), clip: frame, animations: "disabled" });
  await testInfo.attach("geometry", { body: JSON.stringify({ frame, headers, title }, null, 2), contentType: "application/json" });
  await page.getByRole("button", { name: "切换深浅模式" }).click();
  await expect(page.locator("html")).toHaveClass(/\bdark\b/);
  await page.screenshot({ path: testInfo.outputPath("canvas-dark.png"), clip: frame, animations: "disabled" });
  expect(errors).toEqual([]);
}

test("参考尺寸的规模夹具保留原始截图", async ({ page }, testInfo) => {
  await captureScene(page, testInfo);
});

test("同场景夹具由正式页面渲染并保留明暗截图", async ({ page }, testInfo) => {
  await captureScene(page, testInfo, true);
});
