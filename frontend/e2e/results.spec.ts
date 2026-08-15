/**
 * 创建时间: 2026-05-30
 * 任务: 课程设计文档补齐 - 结果页面E2E测试
 * 说明: 测试各分析结果页面的加载和展示：曲线、角色、图谱、主题、时间轴、诊断
 */
import { test, expect } from '@playwright/test';

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
    await page.route(`**/api/novels/${NOVEL_ID}/paragraph-curves**`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          {
            paragraph_id: 0,
            chapter_id: 1,
            paragraph_index: 0,
            position: 0.0,
            pos_density: 0.01,
            neg_density: 0.02,
            net_density: -0.01,
            smoothed_net_density: -0.01,
            surface_tension: 0.3,
            smoothed_surface_tension: 0.3,
          },
          {
            paragraph_id: 1,
            chapter_id: 2,
            paragraph_index: 0,
            position: 1.0,
            pos_density: 0.03,
            neg_density: 0.01,
            net_density: 0.02,
            smoothed_net_density: 0.02,
            surface_tension: 0.5,
            smoothed_surface_tension: 0.5,
          },
        ]),
      });
    });
    await page.goto(`/novels/${NOVEL_ID}/curves?task_id=${TASK_ID}`);
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
          meta: { novel_id: NOVEL_ID, novel_name: '测试小说', total_chapters: 100 },
          phases: [
            { name: '引入期', start: 1, end: 15, ratio: 0.15 },
            { name: '发展期', start: 16, end: 70, ratio: 0.55 },
            { name: '高潮期', start: 71, end: 85, ratio: 0.14 },
            { name: '收束期', start: 86, end: 100, ratio: 0.16 },
          ],
          composite_nodes: [],
          atomic_nodes: [],
          tension_curve: null,
        }),
      });
    });
    await page.goto(`/novels/${NOVEL_ID}/timeline?task_id=${TASK_ID}`);
  });

  test('诊断页应正常加载', async ({ page }) => {
    await page.route(`**/api/novels/${NOVEL_ID}/diagnosis**`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          rerun_required: false,
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
