import { expect, test, type Page } from '@playwright/test';

const novelId = process.env.LIVE_NOVEL_ID;
const taskId = process.env.LIVE_TASK_ID;

test.skip(!novelId || !taskId, 'requires a completed local run');
test.use({ viewport: { width: 1440, height: 900 } });

async function expectDiagnosisPagesFit(page: Page) {
  const passage = page.getByTestId('diagnosis-passage');
  const next = page.getByRole('navigation', { name: '综合诊断分页' }).getByRole('button', { name: '下一页' });
  for (let index = 0; index < 20; index += 1) {
    const size = await passage.evaluate((element) => ({ visible: element.clientHeight, content: element.scrollHeight }));
    expect(size.content, `diagnosis passage ${index + 1} is clipped`).toBeLessThanOrEqual(size.visible + 2);
    if (!(await next.isEnabled())) return;
    await next.click();
  }
  throw new Error('diagnosis pagination did not finish');
}

test('live analysis tabs fit one screen and expose repaired data', async ({ page }) => {
  test.setTimeout(120_000);
  const cases = [
    { route: 'characters', tab: '角色详情', screenshot: 'characters.png' },
    { route: 'topics', tab: '主题总览', screenshot: 'topics.png' },
    { route: 'linguistic', tab: '实体与短语', screenshot: 'linguistic.png' },
    { route: 'timeline', tab: null, screenshot: 'timeline.png' },
    { route: 'diagnosis', tab: '价值主题', screenshot: 'diagnosis.png' },
  ] as const;

  for (const item of cases) {
    await page.goto(`/novels/${novelId}/${item.route}?task_id=${taskId}`);
    if (item.tab) {
      const tab = page.getByRole('tab', { name: item.tab });
      await expect(tab).toBeVisible({ timeout: 30_000 });
      await tab.click();
    }
    if (item.route === 'linguistic') {
      await expect(page.getByText('待审定').first()).toBeVisible({ timeout: 30_000 });
      await expect(page.getByText('待审词表命中')).toBeVisible();
    }
    if (item.route === 'topics') {
      await expect(page.getByText('主题列表 · 25 个')).toBeVisible({ timeout: 30_000 });
    }
    if (item.route === 'diagnosis') {
      await expect(page.getByText(/词典情绪均值/)).toBeVisible({ timeout: 30_000 });
      await expect(page.getByLabel('主题标签，共 25 个')).toBeVisible();
      await page.waitForTimeout(300);
    }
    if (item.route === 'timeline') {
      await page.getByRole('region', { name: '事件轨道' }).getByTestId('timeline-card').first().click();
      await expect(page.getByRole('dialog', { name: '事件详情悬浮框' })).toBeVisible();
      await page.waitForTimeout(300);
    }
    const dimensions = await page.evaluate(() => ({
      viewport: window.innerHeight,
      document: document.documentElement.scrollHeight,
      body: document.body.scrollHeight,
    }));
    expect(dimensions.document, `${item.route} document overflow`).toBeLessThanOrEqual(dimensions.viewport + 2);
    await page.screenshot({ path: test.info().outputPath(item.screenshot), fullPage: false });
    if (item.route === 'diagnosis') await expectDiagnosisPagesFit(page);
    console.log(`${item.route}: ${JSON.stringify(dimensions)}`);
  }

  await page.setViewportSize({ width: 1280, height: 720 });
  for (const item of cases) {
    await page.goto(`/novels/${novelId}/${item.route}?task_id=${taskId}`);
    if (item.tab) await page.getByRole('tab', { name: item.tab }).click();
    if (item.route === 'timeline') {
      await page.getByRole('region', { name: '事件轨道' }).getByTestId('timeline-card').first().click();
      await expect(page.getByRole('dialog', { name: '事件详情悬浮框' })).toBeVisible();
    }
    if (item.route === 'timeline') await page.waitForTimeout(300);
    if (item.route === 'characters') await expect(page.getByText('完整功能构成')).toBeVisible({ timeout: 30_000 });
    if (item.route === 'topics') await expect(page.getByText('主题列表 · 25 个')).toBeVisible({ timeout: 30_000 });
    if (item.route === 'linguistic') await expect(page.getByText('实体类型计数')).toBeVisible({ timeout: 30_000 });
    if (item.route === 'diagnosis') {
      const note = page.getByTestId('diagnosis-emotion-note');
      await expect(note).toBeVisible({ timeout: 30_000 });
      const rect = await note.boundingBox();
      expect((rect?.y ?? 0) + (rect?.height ?? 0), 'compact diagnosis metrics are clipped').toBeLessThanOrEqual(712);
      await page.waitForTimeout(300);
    }
    const dimensions = await page.evaluate(() => ({ viewport: window.innerHeight, document: document.documentElement.scrollHeight }));
    expect(dimensions.document, `${item.route} compact document overflow`).toBeLessThanOrEqual(dimensions.viewport + 2);
    await page.screenshot({ path: test.info().outputPath(`${item.route}-720.png`), fullPage: false });
    if (item.route === 'diagnosis') await expectDiagnosisPagesFit(page);
  }
});

test('all live report tabs stay within a compact screen', async ({ page }) => {
  test.setTimeout(180_000);
  await page.setViewportSize({ width: 1280, height: 720 });
  const routes = [
    { route: 'characters', tabs: ['格局概览', '角色排行', '角色详情'] },
    { route: 'topics', tabs: ['主题总览', '完整主题分布', '主题演进', '主题迁移', '主题情绪'] },
    { route: 'linguistic', tabs: ['表达结构', '实体与短语', '词汇与语义'] },
    { route: 'timeline', tabs: ['事件轨道'] },
    { route: 'diagnosis', tabs: ['综合概览', '价值主题', '角色结构', '伏笔追踪'] },
  ];

  for (const { route, tabs } of routes) {
    await page.goto(`/novels/${novelId}/${route}?task_id=${taskId}`);
    for (const tabName of tabs) {
      const tab = route === 'timeline'
        ? page.getByRole('region', { name: tabName })
        : page.getByRole('tab', { name: tabName });
      await expect(tab).toBeVisible({ timeout: 30_000 });
      if (route !== 'timeline') await tab.click();
      const panel = route === 'timeline' ? tab : page.locator('[role="tabpanel"][data-state="active"]');
      await expect(panel).toBeVisible();
      await expect(panel.getByText(/加载中/)).toHaveCount(0, { timeout: 30_000 });
      if (route === 'topics' && ['主题演进', '主题迁移', '主题情绪'].includes(tabName)) {
        await expect(panel.locator('canvas')).toBeVisible({ timeout: 30_000 });
      }
      await page.waitForTimeout(150);
      const dimensions = await panel.evaluate((element) => ({
        viewport: window.innerHeight,
        document: document.documentElement.scrollHeight,
        panel: element.clientHeight,
        panelContent: element.scrollHeight,
      }));
      expect(dimensions.document, `${route}/${tabName} document overflow`).toBeLessThanOrEqual(dimensions.viewport + 2);
      expect(dimensions.panelContent, `${route}/${tabName} panel overflow`).toBeLessThanOrEqual(dimensions.panel + 2);
      const innerScrollbars = await panel.evaluate((element) => Array.from(element.querySelectorAll<HTMLElement>('*'))
        .filter((child) => {
          const overflow = getComputedStyle(child).overflowY;
          return (overflow === 'auto' || overflow === 'scroll') && child.scrollHeight > child.clientHeight + 2;
        })
        .map((child) => child.getAttribute('aria-label') || child.className || child.tagName));
      expect(innerScrollbars, `${route}/${tabName} inner scrollbars`).toEqual([]);
      console.log(`${route}/${tabName}: ${JSON.stringify(dimensions)}`);
      await page.screenshot({ path: test.info().outputPath(`${route}-${tabName}.png`), fullPage: false });
      if (route === 'timeline') {
        await page.getByRole('region', { name: '事件轨道' }).getByTestId('timeline-card').first().click();
        await expect(page.getByRole('dialog', { name: '事件详情悬浮框' })).toBeVisible();
      }
      if (route === 'topics' && tabName === '主题演进') {
        const chart = panel.locator('canvas');
        const bounds = await chart.boundingBox();
        await chart.hover({ position: { x: (bounds?.width ?? 0) / 2, y: (bounds?.height ?? 0) / 2 } });
        await expect(page.getByText(/加权占比/)).toBeVisible();
      }
      if (route === 'topics' && tabName === '主题迁移') {
        const pagination = page.getByRole('navigation', { name: /变化明细 · 共 \d+ 个分页/ });
        await expect(pagination).toBeVisible();
        await pagination.getByRole('button', { name: '下一页' }).click();
        await expect(pagination).toContainText('2 /');
      }
    }
  }
});
