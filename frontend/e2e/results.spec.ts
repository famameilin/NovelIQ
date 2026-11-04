/**
 * 测试各分析结果页面的加载和展示：曲线、角色、图谱、主题、时间轴、诊断
 */
import { test, expect } from '@playwright/test';
import { createEmotionTrendWindows, createNarrativeStructure, createParagraphCurves } from '../src/mocks/data';

const NOVEL_ID = 'abc12345';
const TASK_ID = 'task5678';

async function mockNovelAndTasks(page: import('@playwright/test').Page) {
  await page.route('**/api/novels/?**', async (route) => {
    if (route.request().method() === 'GET') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items: [{
            novel_id: NOVEL_ID,
            filename: '测试小说.txt',
            status: 'completed',
            title: '测试小说',
            author: '未知作者',
            upload_time: '2026-05-01T10:00:00',
            file_size: 102400,
          }],
          total: 1, page: 1, page_size: 12, total_pages: 1,
        }),
      });
    } else {
      await route.continue();
    }
  });

  await page.route(`**/api/novels/${NOVEL_ID}/tasks`, async (route) => {
    if (route.request().method() === 'GET') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          novel_id: NOVEL_ID,
          tasks: [{
            task_id: TASK_ID,
            novel_id: NOVEL_ID,
            status: 'completed',
            created_at: '2026-05-01T10:00:00',
          }],
        }),
      });
    } else {
      await route.continue();
    }
  });
}

async function mockTaskStatus(page: import('@playwright/test').Page, status: string) {
  await page.route(`**/api/novels/${NOVEL_ID}/tasks/${TASK_ID}/status`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        novel_id: NOVEL_ID,
        task_id: TASK_ID,
        status,
        progress: status === 'completed' ? 100 : 0,
        stage: status === 'completed' ? 'completed' : 'pending',
        message: status === 'completed' ? '分析完成' : '',
        error: null,
      }),
    });
  });
}

test.describe('分析结果页面', () => {
  test.beforeEach(async ({ page }) => {
    await mockNovelAndTasks(page);
    await mockTaskStatus(page, 'completed');
  });

  test('曲线页应正常加载', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.route(`**/api/novels/${NOVEL_ID}/emotion-trend**`, route =>
      route.fulfill({ json: createEmotionTrendWindows(20, null) }));
    await page.route(`**/api/novels/${NOVEL_ID}/tabs/rhythm**`, route => route.fulfill({ json: {
      run_id: TASK_ID, curves: createParagraphCurves(80), narrative_structure: createNarrativeStructure(),
    } }));
    await page.goto(`/novels/${NOVEL_ID}/curves?task_id=${TASK_ID}`);
    await expect(page.getByText('情绪趋势曲线', { exact: true })).toBeVisible();
    await expect(page.getByRole('tabpanel', { name: '情绪趋势' }).locator('canvas').first()).toBeVisible();
    await page.getByRole('tab', { name: '节奏张力', exact: true }).click();
    await expect(page.getByText('节奏张力曲线', { exact: true })).toBeVisible();
    await expect(page.getByRole('tabpanel', { name: '节奏张力' }).locator('canvas').first()).toBeVisible();
    await expect(page.getByText('加载失败', { exact: true })).toHaveCount(0);
    expect(errors).toEqual([]);
  });

  test('角色页应正常加载', async ({ page }) => {
    await page.route(`**/api/novels/${NOVEL_ID}/characters**`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          {
            name: '主角',
            appearance_count: 35,
            dominant_role_function: '主体',
            is_focus_character: true,
            avg_emotion_score: -0.5,
          },
        ]),
      });
    });
    await page.goto(`/novels/${NOVEL_ID}/characters?task_id=${TASK_ID}`);
  });

  test('图谱页应正常加载', async ({ page }) => {
    await page.route(`**/api/novels/${NOVEL_ID}/graph**`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          nodes: [{ id: '1', name: '主角', type: 'character' }],
          edges: [{ source: '1', target: '2', type: '盟友' }],
          events: [],
          summary: {},
          quality: {},
        }),
      });
    });
    await page.goto(`/novels/${NOVEL_ID}/graph?task_id=${TASK_ID}`);
  });

  test('主题页应正常加载', async ({ page }) => {
    await page.route(`**/api/novels/${NOVEL_ID}/topics**`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          { topic_id: 1, words: ['抗争', '命运', '成长'], weight: 5.5, label: '抗争' },
          { topic_id: 2, words: ['爱情', '友情', '信任'], weight: 4.2, label: '情感' },
        ]),
      });
    });
    await page.goto(`/novels/${NOVEL_ID}/topics?task_id=${TASK_ID}`);
  });

  test('时间轴页应正常加载', async ({ page }) => {
    await page.route(`**/api/novels/${NOVEL_ID}/timeline**`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          run_id: TASK_ID, chapters: [{ chapter_id: 1, order: 1, title: '第一章' }],
          through_chapter_id: 1, changes: [], states: [], subjects: [],
          distribution: [], total: 0, next_cursor: null,
        }),
      });
    });
    await page.goto(`/novels/${NOVEL_ID}/timeline?task_id=${TASK_ID}`);
    await expect(page.getByText('没有符合条件的变化', { exact: true })).toBeVisible();
  });

  test('诊断页应正常加载', async ({ page }) => {
    await page.route(`**/api/novels/${NOVEL_ID}/diagnosis**`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          diagnosis: '该叙事以成长为主题，主角经历磨难最终获得力量。',
          genre_labels: ['成长', '奇幻'],
          theme_color: '#4A90D9',
          narrative_arc_type: '白手起家',
        }),
      });
    });

    await page.route(`**/api/novels/${NOVEL_ID}/foreshadowing-threads**`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([]),
      });
    });

    await page.goto(`/novels/${NOVEL_ID}/diagnosis?task_id=${TASK_ID}`);
  });

  test('任务未完成时结果页应显示提示', async ({ page }) => {
    await mockTaskStatus(page, 'running');
    await page.route(`**/api/novels/${NOVEL_ID}/paragraph-curves**`, async (route) => {
      await route.fulfill({
        status: 409,
        contentType: 'application/json',
        body: JSON.stringify({ detail: '分析尚未完成' }),
      });
    });
    await page.route(`**/api/novels/${NOVEL_ID}/metrics/narrative-structure**`, async (route) => {
      await route.fulfill({
        status: 409,
        contentType: 'application/json',
        body: JSON.stringify({ detail: '分析尚未完成' }),
      });
    });
    await page.goto(`/novels/${NOVEL_ID}/curves?task_id=${TASK_ID}`);
    await expect(page.getByText('加载失败').first()).toBeVisible({ timeout: 15000 });
  });
});
