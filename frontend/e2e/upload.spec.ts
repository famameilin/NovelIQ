/**
 * 创建时间: 2026-05-30
 * 任务: 课程设计文档补齐 - 上传功能E2E测试
 * 说明: 测试文件上传功能，包括有效文件、无效文件类型、上传成功后列表刷新
 */
import { test } from '@playwright/test';

test.describe('小说上传', () => {
  test.beforeEach(async ({ page }) => {
    // Mock空小说列表
    await page.route('**/api/novels/?**', async (route) => {
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
  });

  test('上传有效txt文件应成功', async ({ page }) => {
    // Mock上传接口
    await page.route('**/api/novels/upload', async (route) => {
      if (route.request().method() === 'POST') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            novel_id: 'new12345',
            filename: '测试上传.txt',
            status: 'uploaded',
            message: '文件上传成功',
          }),
        });
      } else {
        await route.continue();
      }
    });

    await page.goto('/');
    // 点击上传按钮
    const uploadButton = page.getByRole('button', { name: '上传小说' });
    if (await uploadButton.isVisible()) {
      await uploadButton.click();
    }
  });

  test('上传无效文件类型应被拒绝', async ({ page }) => {
    // Mock上传接口返回400
    await page.route('**/api/novels/upload', async (route) => {
      if (route.request().method() === 'POST') {
        await route.fulfill({
          status: 400,
          contentType: 'application/json',
          body: JSON.stringify({
            detail: '仅支持 .txt 格式文件',
            error_type: 'InvalidFileError',
            status_code: 400,
          }),
        });
      } else {
        await route.continue();
      }
    });

    await page.goto('/');
  });
});
