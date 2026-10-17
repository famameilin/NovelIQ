import { expect, test, type Page } from "@playwright/test";
import type { PlotlineTimelineResponse } from "../src/api/narrativeTypes";

const novelId = process.env.LIVE_NOVEL_ID;
const taskId = process.env.LIVE_TASK_ID;
test.skip(!novelId || !taskId, "需要已完成的本地任务");

/** 检查实际溢出和节点边界，不能用隐藏滚动条或裁掉记录通过验收 */
async function expectTimelineViewport(page: Page) {
  const result = await page.evaluate(() => {
    const scrolls = [...document.querySelectorAll("div")].filter(element => {
      const style = getComputedStyle(element);
      return (/auto|scroll/.test(style.overflowX) && element.scrollWidth > element.clientWidth + 1)
        || (/auto|scroll/.test(style.overflowY) && element.scrollHeight > element.clientHeight + 1);
    });
    const field = document.querySelector('[aria-label="章节变化轨道"]')!.getBoundingClientRect();
    const nodes = [...document.querySelectorAll('[data-testid="timeline-change-node"]')];
    return {
      scrolls: scrolls.map(element => element.className),
      pageFits: document.documentElement.scrollWidth <= innerWidth && document.documentElement.scrollHeight <= innerHeight,
      fieldFits: field.left >= 0 && field.top >= 0 && field.right <= innerWidth + 1 && field.bottom <= innerHeight + 1,
      nodesFit: nodes.every(element => {
        const bounds = element.getBoundingClientRect(), lane = element.parentElement!.getBoundingClientRect();
        return bounds.left >= lane.left - 1 && bounds.right <= lane.right + 1 && bounds.top >= lane.top - 1 && bounds.bottom <= lane.bottom + 1;
      }),
      labelsFit: [...document.querySelectorAll('[data-testid="timeline-node-label"]')].every(element => {
        const bounds = element.getBoundingClientRect(), lane = element.closest("[data-dimension]")!.getBoundingClientRect();
        return bounds.left >= lane.left - 1 && bounds.right <= lane.right + 1 && bounds.top >= lane.top - 1 && bounds.bottom <= lane.bottom + 1;
      }),
      plainNodes: nodes.every(element => {
        const style = getComputedStyle(element);
        return style.backgroundColor === "rgba(0, 0, 0, 0)" && style.boxShadow === "none"
          && [style.borderTopWidth, style.borderRightWidth, style.borderBottomWidth, style.borderLeftWidth].every(width => width === "0px");
      }),
    };
  });
  expect(result).toEqual({ scrolls: [], pageFits: true, fieldFits: true, nodesFit: true, labelsFit: true, plainNodes: true });
}

for (const viewport of [{ width: 1920, height: 924 }, { width: 1440, height: 900 }, { width: 1280, height: 720 }]) {
  test(`真实时间轴无卡片、无滚动且完整可达 ${viewport.width}x${viewport.height}`, async ({ page, request }, testInfo) => {
    test.setTimeout(60_000);
    await page.setViewportSize(viewport);
    const endpoint = `/api/novels/${novelId}/timeline?task_id=${taskId}`;
    const access = await request.get(endpoint);
    expect(access.ok()).toBe(true);
    const initial = await access.json() as PlotlineTimelineResponse;
    const last = initial.chapters.at(-1)!;
    const errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    const requestFailures: Array<{ url: string; error: string | undefined }> = [];
    page.on("requestfailed", failed => requestFailures.push({ url: failed.url(), error: failed.failure()?.errorText }));
    await page.goto(`/novels/${novelId}/timeline?task_id=${taskId}`);
    await expect(page.getByTestId("timeline-change-node").first()).toBeVisible();
    await expectTimelineViewport(page);
    await page.screenshot({ path: testInfo.outputPath("timeline-first-chapter.png") });

    const fullResponse = await request.get(`${endpoint}&through_chapter_id=${last.chapter_id}&limit=1`);
    expect(fullResponse.ok()).toBe(true);
    const full = await fullResponse.json() as PlotlineTimelineResponse;
    const cutoff = page.getByRole("combobox", { name: "阅读截点" });
    await cutoff.selectOption(String(last.chapter_id));
    await expect(page.getByRole("status")).toContainText(`${full.total} 条已发生的变化`);
    await page.getByRole("combobox", { name: "显示窗口" }).selectOption("0");
    expect(await page.getByTestId("timeline-change-node").evaluateAll(nodes => nodes.reduce((sum, node) => sum + Number(node.getAttribute("data-count")), 0))).toBe(full.total);
    await expectTimelineViewport(page);
    await page.screenshot({ path: testInfo.outputPath("timeline-full-book.png") });

    await page.getByRole("combobox", { name: "显示窗口" }).selectOption("4");
    await page.getByRole("button", { name: "向前浏览章节" }).click();
    await expect(page.getByLabel("章节变化轨道")).toContainText(`当前显示第 ${initial.chapters.at(-7)!.order}–${initial.chapters.at(-4)!.order} 章`);
    await expect(cutoff).toHaveValue(String(last.chapter_id));
    // 查询接口期间节点可能重新渲染，按已核对的章节名称点击，避免 first 定位到另一章
    const nodeLabel = (await page.getByTestId("timeline-change-node").first().getAttribute("aria-label"))!;
    const node = page.getByRole("button", { name: nodeLabel, exact: true });
    const chapterOrder = Number(nodeLabel.match(/^(\d+) /)![1]);
    const chapter = initial.chapters.find(item => item.order === chapterOrder)!;
    const groupResponse = await request.get(`${endpoint}&through_chapter_id=${chapter.chapter_id}&window_start_chapter_id=${chapter.chapter_id}&dimension=plot`);
    expect(groupResponse.ok()).toBe(true);
    const group = await groupResponse.json() as PlotlineTimelineResponse;
    await node.click();
    const groupDialog = page.getByRole("dialog", { name: "本章变化" });
    await expect(groupDialog).toContainText(`第 ${chapter.order} 章 · 情节推进`);
    await expect(groupDialog).toContainText(`${group.total} 条`);
    await groupDialog.getByText(group.changes[0].title, { exact: true }).click();
    const detail = page.getByRole("dialog", { name: "变化详情" });
    await expect(detail).toContainText(group.changes[0].title);
    await detail.getByRole("button", { name: "阅读原文", exact: true }).click();
    const reader = page.getByRole("dialog", { name: "章节原文" });
    await expect(reader).toBeVisible();
    await expect(reader.getByText("正在读取原文…")).toHaveCount(0);
    await reader.getByRole("button", { name: "关闭原文", exact: true }).click();
    await detail.getByRole("button", { name: "关闭变化详情" }).click();
    await page.getByRole("button", { name: "定位阅读章节" }).click();
    await expectTimelineViewport(page);
    await page.screenshot({ path: testInfo.outputPath("timeline-last-chapter.png") });

    await page.getByRole("button", { name: "查看情节推进全部主体" }).click();
    await expect(page.getByRole("dialog", { name: "情节推进 · 当前状态" })).toBeVisible();
    await page.getByRole("button", { name: "关闭情节推进 · 当前状态" }).click();
    await page.getByRole("textbox", { name: "搜索截点内变化" }).fill("__无此变化_布局验收__");
    await expect(page.getByRole("status")).toContainText("此截点内没有符合条件的变化");
    await expectTimelineViewport(page);
    expect(errors).toEqual([]);
    await testInfo.attach("request-failures", { body: JSON.stringify(requestFailures, null, 2), contentType: "application/json" });
    expect(requestFailures.filter(failure => failure.error !== "net::ERR_ABORTED")).toEqual([]);
  });
}
