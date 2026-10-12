import { expect, test, type Page, type Locator } from "@playwright/test";
import type { DiagnosisResult, ForeshadowingTree } from "../src/api/types";

const novelId = process.env.LIVE_NOVEL_ID;
const taskId = process.env.LIVE_TASK_ID;
test.skip(!novelId || !taskId, "需要已完成的本地任务");

/** 同时检查真实滚动、隐藏溢出和正文边界，不能靠隐藏滚动条通过验收 */
async function expectReportLayout(page: Page) {
  await expect(page.locator('[role="tabpanel"][data-state="active"]')).toHaveCSS("opacity", "1");
  await expect.poll(() => page.evaluate(() => {
    const main = document.querySelector("main")!;
    const panel = document.querySelector('[role="tabpanel"][data-state="active"]')!;
    const bounds = panel.getBoundingClientRect();
    const visible = (element: Element) => element.getClientRects().length > 0;
    const scrolls = [...document.querySelectorAll("div")].filter(element => {
      const style = getComputedStyle(element);
      return (/auto|scroll/.test(style.overflowY) && element.scrollHeight > element.clientHeight + 1)
        || (/auto|scroll/.test(style.overflowX) && element.scrollWidth > element.clientWidth + 1);
    });
    const clipped = [...panel.querySelectorAll("div, section, p")].filter(element => {
      if (!visible(element)) return false;
      const style = getComputedStyle(element);
      return /hidden|clip/.test(style.overflowY) && element.scrollHeight > element.clientHeight + 2;
    });
    const readers = [...panel.querySelectorAll('[data-testid="diagnosis-text-reader"] > div:first-child')];
    const controls = [...panel.querySelectorAll("button, nav, canvas")].filter(visible);
    return {
      pageFits: document.documentElement.scrollWidth <= innerWidth && document.documentElement.scrollHeight <= innerHeight
        && main.getBoundingClientRect().bottom <= innerHeight + 1,
      scrollCount: scrolls.length,
      noClippedText: clipped.length === 0 && readers.every(element => element.scrollHeight <= element.clientHeight + 1),
      controlsFit: controls.every(element => {
        const rect = element.getBoundingClientRect();
        return rect.top >= bounds.top - 1 && rect.bottom <= bounds.bottom + 1 && rect.left >= bounds.left - 1 && rect.right <= bounds.right + 1;
      }),
    };
  })).toEqual({ pageFits: true, scrollCount: 0, noClippedText: true, controlsFit: true });
}

/** 实际翻到每一页，合并后核对末段和完整依据仍然可达 */
async function readAllPages(page: Page, reader: Locator): Promise<string> {
  let collected = "";
  for (let index = 0; index < 100; index++) {
    await expectReportLayout(page);
    collected += await reader.locator(":scope > div").first().textContent();
    const next = reader.getByRole("button", { name: "下一页" });
    if (!await next.count() || !await next.isEnabled()) return collected;
    await next.click();
  }
  throw new Error("文字分页超过验收上限");
}

for (const viewport of [{ width: 1920, height: 924 }, { width: 1440, height: 900 }, { width: 1280, height: 720 }]) {
  test(`真实诊断四个页签无滚动且完整可达 ${viewport.width}x${viewport.height}`, async ({ page, request }, testInfo) => {
    test.setTimeout(60_000);
    await page.setViewportSize(viewport);
    const diagnosisResponse = await request.get(`/api/novels/${novelId}/diagnosis?task_id=${taskId}`);
    const treesResponse = await request.get(`/api/novels/${novelId}/foreshadowing-trees?task_id=${taskId}`);
    expect(diagnosisResponse.ok()).toBe(true);
    expect(treesResponse.ok()).toBe(true);
    const diagnosis = await diagnosisResponse.json() as DiagnosisResult;
    const trees = await treesResponse.json() as ForeshadowingTree[];
    const errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.goto(`/novels/${novelId}/diagnosis?task_id=${taskId}`);
    await expect(page.getByTestId("diagnosis-passage")).toBeVisible();
    await expectReportLayout(page);
    await page.screenshot({ path: testInfo.outputPath("overview.png") });
    const full = await readAllPages(page, page.getByRole("tabpanel", { name: "综合概览" }).getByTestId("diagnosis-passage").locator(".."));
    expect(full).toContain(diagnosis.diagnosis!.trim().slice(-50));

    await page.getByRole("tab", { name: "价值主题" }).click();
    await expect(page.getByTestId("value-logic-passage")).toBeVisible();
    await expectReportLayout(page);
    await page.screenshot({ path: testInfo.outputPath("value-topic.png") });
    expect(await readAllPages(page, page.getByTestId("value-logic-passage").locator(".."))).toContain(diagnosis.value_logic_reason!.trim());
    const topics = page.getByLabel(`主题标签，共 ${Object.keys(diagnosis.topic_labels ?? {}).length} 个`);
    const labels: string[] = [];
    for (let index = 0; index < 100; index++) {
      labels.push(...await topics.locator("span[title]").evaluateAll(nodes => nodes.map(node => node.getAttribute("title")!)));
      const next = topics.getByRole("button", { name: "下一页" });
      if (!await next.count() || !await next.isEnabled()) break;
      await next.click();
      await expectReportLayout(page);
    }
    expect(labels).toEqual(Object.values(diagnosis.topic_labels ?? {}));

    await page.getByRole("tab", { name: "角色结构" }).click();
    const castPanel = page.getByRole("tabpanel", { name: "角色结构" });
    await expect(castPanel.getByText("人物诊断", { exact: true })).toBeVisible();
    await expect(page.getByText(`${Object.keys(diagnosis.arc_scores ?? {}).length} 人 · 满分 10`)).toBeVisible();
    await expect(page.locator("canvas")).toBeVisible();
    await page.waitForTimeout(900);
    await expectReportLayout(page);
    await page.screenshot({ path: testInfo.outputPath("cast-structure.png") });
    expect(await readAllPages(page, castPanel.getByTestId("diagnosis-passage").locator(".."))).toContain("【人物】");

    await page.getByRole("tab", { name: "伏笔追踪" }).click();
    const panel = page.getByRole("tabpanel", { name: "伏笔追踪" });
    await expectReportLayout(page);
    await page.screenshot({ path: testInfo.outputPath("foreshadowing.png") });
    const descriptions: string[] = [];
    for (let index = 0; index < 100; index++) {
      descriptions.push(...await panel.locator("[data-diagnosis-preview]").allTextContents());
      const next = panel.getByRole("navigation", { name: "伏笔线索分页" }).getByRole("button", { name: "下一页" });
      if (!await next.count() || !await next.isEnabled()) break;
      await next.click();
      await expectReportLayout(page);
    }
    expect(descriptions).toEqual(trees.map(tree => tree.description));
    await panel.getByRole("button").filter({ hasText: trees.at(-1)!.description }).click();
    expect(await readAllPages(page, panel.getByTestId("foreshadowing-detail-passage").locator(".."))).toContain(trees.at(-1)!.description);
    await page.screenshot({ path: testInfo.outputPath("foreshadowing-last.png") });
    const filter = page.getByRole("group", { name: "伏笔状态筛选" });
    for (const [status, label] of [["open", "待回收"], ["reinforced", "持续强化"], ["likely_paid_off", "疑似回收"]]) {
      await filter.getByRole("button", { name: label, exact: true }).click();
      await expectReportLayout(page);
      const matches = trees.filter(tree => tree.status === status);
      const displayed = await panel.locator("[data-diagnosis-preview]").allTextContents();
      expect(displayed).toEqual(matches.slice(0, displayed.length).map(tree => tree.description));
    }
    expect(errors).toEqual([]);
  });
}

for (const viewport of [{ width: 1440, height: 900 }, { width: 1280, height: 720 }]) {
  test(`五百人名单无滚动且搜索可直达末项 ${viewport.width}x${viewport.height}`, async ({ page, request }, testInfo) => {
    await page.setViewportSize(viewport);
    const response = await request.get(`/api/novels/${novelId}/diagnosis?task_id=${taskId}`);
    expect(response.ok()).toBe(true);
    const original = await response.json() as DiagnosisResult;
    const names = Array.from({ length: 500 }, (_, index) => `人物${String(index + 1).padStart(3, "0")}`);
    await page.route(`**/api/novels/${novelId}/diagnosis?*`, route => route.fulfill({ json: {
      ...original, core_cast: names, main_characters: names,
      arc_scores: Object.fromEntries(names.map((name, index) => [name, 10 - index / 100])),
    } }));
    await page.goto(`/novels/${novelId}/diagnosis?task_id=${taskId}`);
    await page.getByRole("tab", { name: "角色结构" }).click();
    const search = page.getByRole("textbox", { name: "核心角色姓名搜索" });
    await expect(search).toBeVisible();
    await expectReportLayout(page);
    await expect(page.getByText("人物013", { exact: true })).toHaveCount(0);
    await search.fill("人物500");
    await expect(page.getByText("人物500", { exact: true })).toBeVisible();
    await expect(page.getByText("匹配 1 / 500 人")).toBeVisible();
    await expectReportLayout(page);
    await page.waitForTimeout(900);
    await page.screenshot({ path: testInfo.outputPath("cast-500.png") });
  });
}

test("长判断依据与多行文本分页后无滚动且字符完整", async ({ page, request }) => {
  test.setTimeout(60_000);
  await page.setViewportSize({ width: 1280, height: 720 });
  const response = await request.get(`/api/novels/${novelId}/foreshadowing-trees?task_id=${taskId}`);
  const trees = await response.json() as ForeshadowingTree[];
  const reason = "必须保留的完整判断依据。\n".repeat(20).trim();
  await page.route(`**/api/novels/${novelId}/foreshadowing-trees?*`, route => route.fulfill({ json: [{ ...trees[0], latest_reason: reason }] }));
  await page.goto(`/novels/${novelId}/diagnosis?task_id=${taskId}`);
  await page.getByRole("tab", { name: "伏笔追踪" }).click();
  await expect(page.getByTestId("foreshadowing-detail-passage")).toBeVisible();
  const full = await readAllPages(page, page.getByTestId("foreshadowing-detail-passage").locator(".."));
  expect(full).toContain(reason);
});
