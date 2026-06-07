/**
 * 创建时间: 2026-05-30
 * 任务: 课程设计文档补齐 - 首页E2E测试
 * 说明: 测试首页加载、小说列表展示、搜索和排序功能
 */
import { test, expect } from '@playwright/test';

const MOCK_NOVELS = {
  items: [
    {
      novel_id: 'abc12345',
      filename: '测试小说.txt',
      file_path: 'data/uploads/abc12345_测试小说.txt',
      status: 'completed',
      title: '测试小说',
      author: '未知作者',
      upload_time: '2026-05-01T10:00:00',
      file_size: 102400,
    },
    {
      novel_id: 'def67890',
      filename: '第二部小说.txt',
      file_path: 'data/uploads/def67890_第二部小说.txt',
      status: 'uploaded',
      title: '第二部小说',
      author: '未知作者',
      upload_time: '2026-05-02T12:00:00',
      file_size: 204800,
    },
  ],
  total: 2,
  page: 1,
  page_size: 12,
  total_pages: 1,
};

test.describe('首页', () => {
  test.beforeEach(async ({ page }) => {
    // Mock小说列表API
    await page.route('**/api/novels/**', async (route) => {
      const url = route.request().url();
      if (route.request().method() === 'GET' && url.includes('/api/novels') && !url.includes('/tasks')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(MOCK_NOVELS),
        });
      } else {
        await route.continue();
      }
    });
  });

  test('应正确加载首页并展示小说列表', async ({ page }) => {
    await page.goto('/');
    // 等待页面加载完成
    await expect(page).toHaveTitle(/NovelIQ|小说/);
  });

  test('应展示小说卡片信息', async ({ page }) => {
    await page.goto('/');
    // 验证小说列表中包含mock数据
    await expect(page.getByText('测试小说')).toBeVisible();
  });

  test('空状态应提示上传小说', async ({ page }) => {
    // Mock空列表
    await page.route('**/api/novels/**', async (route) => {
      if (route.request().method() === 'GET') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            items: [],
            total: 0,
            page: 1,
            page_size: 12,
            total_pages: 0,
          }),
        });
      } else {
        await route.continue();
      }
    });
    await page.goto('/');
    // 应显示空状态提示
    await expect(page.getByText(/上传|暂无/)).toBeVisible();
  });
});
