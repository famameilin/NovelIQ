import { expect, test } from '@playwright/test';

const novelId = '018bcfe5-6800-7000-8000-000000000001';
const taskId = 'test0032';

test('桌面任务仅展示状态，模型输出按真实 Agent 分流', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (!path.startsWith('/api/')) { await route.continue(); return; }
    if (path.endsWith(`/events/tasks/${taskId}`)) {
      const messages = [
        { type: 'snapshot', data: {
          cursor: 1, run_id: 'run-runtime', task_id: taskId, status: 'running', stage: 'diagnose', error: null,
          stages: { diagnose: { stage: 'diagnose', status: 'running' } }, models: [], seats: [], executions: {},
        } },
        { type: 'llm_output', data: { invocation_id: 'case-agent', stage: 'diagnose', sub_stage: 'case', content: '已读取原文并核对案例' } },
        { type: 'llm_output', data: { invocation_id: 'report-agent', stage: 'diagnose', sub_stage: 'report', content: '报告 Agent 正在整理结论' } },
      ];
      await route.fulfill({ status: 200, contentType: 'text/event-stream', body: messages.map((message, index) => `id: ${index + 1}\nevent: ${message.type}\ndata: ${JSON.stringify(message.data)}\n\n`).join('') });
      return;
    }
    const task = { novel_id: novelId, task_id: taskId, status: 'running' };
    const novel = { novel_id: novelId, filename: '桌面验收.txt', title: '桌面验收', author: null, upload_time: '2026-10-19T00:00:00', file_size: 128, status: 'running' };
    const body = path.endsWith('/status') ? task
      : path.endsWith('/tasks') ? { novel_id: novelId, tasks: [task] }
      : path.endsWith(novelId) ? novel
      : { items: [novel], total: 1, page: 1, page_size: 12, total_pages: 1 };
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
  await page.goto(`/novels/${novelId}?task_id=${taskId}`);
  await expect(page.getByRole('region', { name: '分析工作台' }), errors.join(' | ')).toBeVisible({ timeout: 15000 });
  await expect(page.getByRole('button', { name: '停止分析' })).toBeVisible();
  await page.getByRole('combobox', { name: '选择执行记录' }).selectOption('report-agent');
  await expect(page.getByText('报告 Agent 正在整理结论')).toBeVisible();
  await page.getByRole('combobox', { name: '选择执行记录' }).selectOption('case-agent');
  await expect(page.getByText('已读取原文并核对案例')).toBeVisible();
  await expect(page.getByRole('progressbar')).toHaveCount(0);
  await page.screenshot({ path: test.info().outputPath('runtime-status-desktop.png'), fullPage: false });
  await page.reload();
  await expect(page.getByRole('region', { name: '分析工作台' })).toBeVisible();
  await page.getByRole('combobox', { name: '选择执行记录' }).selectOption('case-agent');
  await expect(page.getByText('已读取原文并核对案例')).toBeVisible();
  expect(errors).toEqual([]);
});
