import { expect, test } from '@playwright/test';
import type { EventTimelineResponse } from '../src/api/types';

const novelId = process.env.LIVE_NOVEL_ID;
const taskId = process.env.LIVE_TASK_ID;

test.skip(!novelId || !taskId, 'requires a completed local run');

for (const viewport of [{ width: 1280, height: 720 }, { width: 1440, height: 900 }]) {
  test(`live continuous timeline and event popover at ${viewport.width}x${viewport.height}`, async ({ page, request }) => {
    test.setTimeout(90_000);
    const response = await request.get(`/api/novels/${novelId}/timeline?task_id=${taskId}&include_curve=true`);
    expect(response.ok()).toBeTruthy();
    const timeline = await response.json() as EventTimelineResponse;
    expect(timeline.nodes.length).toBeGreaterThan(1);

    await page.setViewportSize(viewport);
    await page.goto(`/novels/${novelId}/timeline?task_id=${taskId}`);
    const track = page.getByRole('region', { name: '事件轨道' });
    await expect(track).toBeVisible({ timeout: 30_000 });
    await expect(track.getByTestId('timeline-card')).toHaveCount(timeline.nodes.length);
    await expect(page.getByRole('navigation', { name: '事件轨道分页' })).toHaveCount(0);
    await page.screenshot({ path: test.info().outputPath(`timeline-restored-track-${viewport.width}x${viewport.height}.png`), fullPage: false });

    const last = track.getByTestId('timeline-card').last();
    const lastTreeId = await last.getAttribute('data-tree-id');
    await last.click();
    const detail = page.getByRole('dialog', { name: '事件详情悬浮框' });
    await expect(detail).toBeVisible();
    await expect(detail.locator(':scope > div')).toHaveCSS('opacity', '1');
    await expect(page).toHaveURL(new RegExp(`tree_id=${encodeURIComponent(lastTreeId ?? '')}`));
    await page.screenshot({ path: test.info().outputPath(`timeline-restored-detail-${viewport.width}x${viewport.height}.png`), fullPage: false });

    const bounds = await page.evaluate(() => ({
      bodyWidth: document.body.scrollWidth, bodyHeight: document.body.scrollHeight,
      viewportWidth: window.innerWidth, viewportHeight: window.innerHeight,
    }));
    expect(bounds.bodyWidth).toBeLessThanOrEqual(bounds.viewportWidth + 2);
    expect(bounds.bodyHeight).toBeLessThanOrEqual(bounds.viewportHeight + 2);
    await page.getByRole('button', { name: '关闭事件详情' }).click();
    await expect(page.getByRole('dialog', { name: '事件详情悬浮框' })).toHaveCount(0);
    await expect(track.getByTestId('timeline-card')).toHaveCount(timeline.nodes.length);
  });
}

test('tree-level timeline deep link opens the matching event on the timeline', async ({ page, request }) => {
  test.setTimeout(60_000);
  const response = await request.get(`/api/novels/${novelId}/timeline?task_id=${taskId}&include_curve=true`);
  expect(response.ok()).toBeTruthy();
  const timeline = await response.json() as EventTimelineResponse;
  const node = timeline.nodes[0];
  expect(node).toBeTruthy();
  await page.goto(`/novels/${novelId}/timeline?task_id=${taskId}&tree_id=${encodeURIComponent(node.tree_id)}&event_id=${encodeURIComponent(node.root_event_id)}`);
  await expect(page.getByRole('dialog', { name: '事件详情悬浮框' })).toBeVisible();
  expect(new URL(page.url()).pathname).toBe(`/novels/${novelId}/timeline`);
});
