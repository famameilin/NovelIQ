import { expect, test, type Page } from '@playwright/test';
import type { EventForestResponse, EventForestTree } from '../src/api/types';

const novelId = process.env.LIVE_NOVEL_ID;
const taskId = process.env.LIVE_TASK_ID;

test.skip(!novelId || !taskId, 'requires a completed local run');

async function expectOneScreen(page: Page) {
  const bounds = await page.evaluate(() => ({
    bodyWidth: document.body.scrollWidth,
    bodyHeight: document.body.scrollHeight,
    viewportWidth: window.innerWidth,
    viewportHeight: window.innerHeight,
  }));
  expect(bounds.bodyWidth).toBeLessThanOrEqual(bounds.viewportWidth + 2);
  expect(bounds.bodyHeight).toBeLessThanOrEqual(bounds.viewportHeight + 2);
}

for (const viewport of [{ width: 1280, height: 720 }, { width: 1440, height: 900 }]) {
  test(`live growth forest, dense tree and manuscript at ${viewport.width}x${viewport.height}`, async ({ page, request }) => {
    test.setTimeout(90_000);
    const response = await request.get(`/api/novels/${novelId}/event-forest?task_id=${taskId}`);
    expect(response.ok()).toBeTruthy();
    const forest = await response.json() as EventForestResponse;
    const sideCount = (item: EventForestTree) => item.secondary_groups.reduce((count, group) => count + group.branch.length, 0);
    const tree = [...forest.event_trees].filter((item) => sideCount(item) > 0).sort((a, b) =>
      sideCount(b) - sideCount(a) || b.main_chain.length - a.main_chain.length,
    )[0];
    const group = tree.secondary_groups.find((item) => item.branch.length > 0);
    expect(group).toBeTruthy();
    if (!group) throw new Error('selected event tree has no secondary branch');
    const branchId = group.branch[0];
    const branch = forest.event_nodes.find((node) => node.event_id === branchId);
    expect(branch?.parent_event_id).toBe(group.target_event_id);

    await page.setViewportSize(viewport);
    await page.goto(`/novels/${novelId}/event-trees?task_id=${taskId}`);
    const forestView = page.getByRole('region', { name: '整片事件森林' });
    await expect(forestView).toBeVisible({ timeout: 30_000 });
    await expect(forestView.locator('[data-tree-id]')).toHaveCount(forest.event_trees.length);
    await expect(page.getByRole('button', { name: '阅读本章原文' })).toHaveCount(0);
    await page.screenshot({ path: test.info().outputPath(`event-growth-forest-${viewport.width}x${viewport.height}.png`), fullPage: false });
    await expectOneScreen(page);

    await forestView.locator(`[data-tree-id="${tree.tree_id}"]`).click();
    const structure = page.getByRole('region', { name: '事件树结构' });
    await expect(structure).toBeVisible();
    await expect(structure.locator(`[data-parent-id="${group.target_event_id}"][data-child-id="${branchId}"]`)).toHaveCount(1);
    await structure.getByRole('button', { name: new RegExp(branch.description.slice(0, 10)) }).click();
    await expect(page.getByRole('complementary', { name: '事件节点详情' }).getByText(branch.description)).toBeVisible();
    await expect(page.getByRole('region', { name: '树间因果联系' }).getByText(/没有这棵树的树间因果联系/)).toBeVisible();
    await page.screenshot({ path: test.info().outputPath(`event-growth-tree-${viewport.width}x${viewport.height}.png`), fullPage: false });
    await expectOneScreen(page);

    const longestChain = [...forest.event_trees].sort((a, b) => b.main_chain.length - a.main_chain.length)[0];
    await page.goto(`/novels/${novelId}/event-trees?task_id=${taskId}&tree_id=${longestChain.tree_id}`);
    await expect(page.getByRole('region', { name: '事件树结构' }).locator('[data-event-id]')).toHaveCount(longestChain.main_chain.length + sideCount(longestChain));
    await page.screenshot({ path: test.info().outputPath(`event-growth-chain-${viewport.width}x${viewport.height}.png`), fullPage: false });
    await expectOneScreen(page);

    await page.goto(`/novels/${novelId}/event-trees?task_id=${taskId}&tree_id=${tree.tree_id}&event_id=${branchId}`);
    await expect(page.getByRole('button', { name: '阅读本章原文' })).toBeVisible();

    await page.getByRole('button', { name: '阅读本章原文' }).click();
    const reader = page.getByRole('dialog', { name: '章节原文' });
    await expect(reader).toBeVisible();
    await expect(reader.getByText(/只有章节级依据/)).toBeVisible();
    await expect.poll(() => reader.locator('[data-paragraph-id]').count()).toBeGreaterThan(0);
    expect(await reader.locator('[data-paragraph-id].bg-primary\\/10').count()).toBe(0);
    await page.screenshot({ path: test.info().outputPath(`event-growth-source-${viewport.width}x${viewport.height}.png`), fullPage: false });

    await expectOneScreen(page);
    const article = await reader.getByRole('article', { name: '本页原文' }).evaluate((element) => ({
      contentHeight: element.scrollHeight, pageHeight: element.clientHeight,
    }));
    expect(article.contentHeight).toBeLessThanOrEqual(article.pageHeight + 2);
  });
}

test('tree-level timeline link keeps its event detail on the timeline', async ({ page, request }) => {
  test.setTimeout(60_000);
  const response = await request.get(`/api/novels/${novelId}/event-forest?task_id=${taskId}`);
  expect(response.ok()).toBeTruthy();
  const forest = await response.json() as EventForestResponse;
  const tree = forest.event_trees[0];
  expect(tree).toBeTruthy();
  await page.goto(`/novels/${novelId}/timeline?task_id=${taskId}&tree_id=${encodeURIComponent(tree.tree_id)}&event_id=${encodeURIComponent(tree.root_event_id)}`);
  await expect(page.getByRole('dialog', { name: '事件详情悬浮框' })).toBeVisible();
  const url = new URL(page.url());
  expect(url.pathname).toBe(`/novels/${novelId}/timeline`);
  expect(url.searchParams.get('task_id')).toBe(taskId);
  expect(url.searchParams.get('tree_id')).toBe(tree.tree_id);
  expect(url.searchParams.get('event_id')).toBe(tree.root_event_id);
});
