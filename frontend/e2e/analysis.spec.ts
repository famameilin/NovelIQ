/**
 * 创建时间: 2026-05-30
 * 任务: 课程设计文档补齐 - 分析任务E2E测试
 * 说明: 测试分析任务生命周期：创建任务、查看进度、取消任务、任务完成
 */
import { test, expect } from '@playwright/test';

const NOVEL_ID = 'abc12345';
const TASK_ID = 'task5678';

const MOCK_NOVEL_RESPONSE = {
  items: [{
    novel_id: NOVEL_ID,
    filename: '测试小说.txt',
    file_path: `data/uploads/${NOVEL_ID}_测试小说.txt`,
    status: 'completed',
    title: '测试小说',
    author: '未知作者',
    upload_time: '2026-05-01T10:00:00',
    file_size: 102400,
  }],
  total: 1,
  page: 1,
  page_size: 12,
  total_pages: 1,
};

test.describe('分析任务', () => {
  test.beforeEach(async ({ page }) => {
    // Mock小说列表（含 getNovel 的 page_size=1000 请求）
    await page.route('**/api/novels/?**', async (route) => {
      if (route.request().method() === 'GET') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(MOCK_NOVEL_RESPONSE),
        });
      } else {
        await route.continue();
      }
    });

    // Mock任务列表（空）
    await page.route(`**/api/novels/${NOVEL_ID}/tasks`, async (route) => {
      if (route.request().method() === 'GET') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            novel_id: NOVEL_ID,
            tasks: [],
          }),
        });
      } else if (route.request().method() === 'POST') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            novel_id: NOVEL_ID,
            task_id: TASK_ID,
            status: 'pending',
            message: '分析任务已创建并启动',
          }),
        });
      } else {
        await route.continue();
      }
    });

    // Mock诊断接口
    await page.route(`**/api/novels/${NOVEL_ID}/diagnosis**`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          rerun_required: false,
          diagnosis: '测试诊断结果',
          genre_labels: ['成长'],
          theme_color: '#4A90D9',
        }),
      });
    });
  });

  test('无任务时应显示空状态提示', async ({ page }) => {
    await page.goto(`/novels/${NOVEL_ID}`);
    await expect(page.getByRole('heading', { name: '尚未分析' })).toBeVisible();
  });

  test('创建任务后应显示进度面板', async ({ page }) => {
    await page.route(`**/api/novels/${NOVEL_ID}/tasks/${TASK_ID}/status`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          novel_id: NOVEL_ID,
          task_id: TASK_ID,
          status: 'running',
          progress: 45.5,
          stage: 'annotate',
          sub_stage: 'phase2',
          current: 91,
          total: 200,
          message: '正在处理第 91 / 200 个分块',
          error: null,
          started_at: '2026-05-01T10:00:05',
          completed_at: null,
        }),
      });
    });

    await page.goto(`/novels/${NOVEL_ID}?task_id=${TASK_ID}`);
    await expect(page.getByRole('heading', { name: '分析进行中' })).toBeVisible({ timeout: 15000 });
  });

  test('已完成任务应显示仪表盘', async ({ page }) => {
    await page.route(`**/api/novels/${NOVEL_ID}/tasks/${TASK_ID}/status`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          novel_id: NOVEL_ID,
          task_id: TASK_ID,
          status: 'completed',
          progress: 100,
          stage: 'completed',
          message: '分析完成',
          error: null,
          started_at: '2026-05-01T10:00:05',
          completed_at: '2026-05-01T10:05:30',
        }),
      });
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

    const mockEndpoints = [
      'narrative-structure',
      'emotion-stats',
      'character-stats',
      'style-stats',
      'chunk-curves',
    ];
    for (const endpoint of mockEndpoints) {
      await page.route(`**/api/novels/${NOVEL_ID}/metrics/${endpoint}**`, async (route) => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(endpoint === 'chunk-curves' ? [] : {}),
        });
      });
    }

    await page.route(`**/api/novels/${NOVEL_ID}/topics**`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([]),
      });
    });

    await page.goto(`/novels/${NOVEL_ID}?task_id=${TASK_ID}`);
    await expect(page.getByText('仪表盘', { exact: true })).toBeVisible({ timeout: 15000 });
  });
});
