import { expect, test } from '@playwright/test';

const novelId = process.env.QUEUE_AGENT_NOVEL_ID;
const taskId = process.env.QUEUE_AGENT_TASK_ID;
test.skip(!novelId || !taskId, '需要隔离 schema 的真实 Agent 保存结果');

test('共享案例、独立工作和跨章连接使用真实 API，刷新后保持一致', async ({ page, request }) => {
  const failures: string[] = [];
  page.on('pageerror', error => failures.push(error.message));
  page.on('response', response => {
    if (response.url().includes('/api/') && response.status() >= 500) failures.push(`${response.status()} ${response.url()}`);
  });
  await page.setViewportSize({ width: 1440, height: 900 });
  const response = await request.get(`/api/novels/${novelId}/pipeline?task_id=${taskId}`);
  expect(response.ok()).toBe(true);
  const saved = await response.json();
  expect(saved.works.every((work: {state: string}) => work.state === 'saved')).toBe(true);
  await page.goto(`/novels/${novelId}/event-trees?task_id=${taskId}`);
  const boundary = page.getByLabel('分析可见边界');
  await expect(boundary.getByText('已完成 2/2 章 · 已保存 2 项工作')).toBeVisible();
  await expect(boundary.getByText(/已确定 1/)).toBeVisible();
  await boundary.getByText('查看案例').click();
  await expect(boundary.getByText('旧信的用途')).toBeVisible();
  await boundary.getByText('查看事件关联').click();
  await expect(boundary.getByText('拾得旧信 → 读懂旧信')).toBeVisible();
  await expect(boundary.getByText('主因', { exact: true })).toBeVisible();
  await page.getByRole('region', { name: '整片事件森林' }).getByRole('button', { name: /拾得旧信/ }).click();
  await expect(page.getByRole('region', { name: '事件树结构' })).toBeVisible();
  await page.screenshot({ path: test.info().outputPath('queue-agent-workspace.png'), fullPage: false });
  await page.reload();
  await expect(boundary.getByText('已完成 2/2 章 · 已保存 2 项工作')).toBeVisible();
  expect(failures).toEqual([]);
});

test('恢复后的真实 SSE 回放隔离旧终态和 invocation，保留其他已保存工作', async ({ page, request }) => {
  const prepared = await request.post('http://127.0.0.1:8016/__queue_agent_review_isolation');
  expect(prepared.ok()).toBe(true);
  await page.goto(`/novels/${novelId}/event-trees?task_id=${taskId}`);
  for (let attempt = 0; attempt < 2; attempt++) {
    if (attempt) await page.reload();
    const replay = await page.evaluate(async ({ novel, task }) => {
      const moduleUrl = '/src/store/streamStore.ts';
      const { useStreamStore } = await import(/* @vite-ignore */ moduleUrl);
      useStreamStore.getState().resetStreamForTask(task);
      return new Promise<{ outputs: string[]; oldTerminals: number; resets: number }>((resolve, reject) => {
        const source = new EventSource(`/api/novels/${novel}/events/tasks/${task}`);
        let oldTerminals = 0;
        let resets = 0;
        const timer = setTimeout(() => { source.close(); reject(new Error('真实 SSE 回放未完成')); }, 5000);
        source.addEventListener('task_reset', () => { resets++; });
        for (const type of ['task_cancelled', 'task_error', 'task_complete']) {
          source.addEventListener(type, () => { oldTerminals++; });
        }
        source.addEventListener('work_reset', event => {
          useStreamStore.getState().resetWorkOutput(JSON.parse((event as MessageEvent).data));
        });
        source.addEventListener('llm_output', event => {
          useStreamStore.getState().appendLLMOutput(JSON.parse((event as MessageEvent).data));
        });
        source.addEventListener('stage_start', event => {
          const data = JSON.parse((event as MessageEvent).data);
          if (data.message !== 'REVIEW_CURRENT_STAGE') return;
          clearTimeout(timer);
          source.close();
          const outputs = Array.from(useStreamStore.getState().llmOutputs.values(),
            (group: { outputText: string }) => group.outputText);
          resolve({ outputs, oldTerminals, resets });
        });
      });
    }, { novel: novelId!, task: taskId! });
    expect(replay.oldTerminals).toBe(0);
    expect(replay.resets).toBe(1);
    expect(replay.outputs).toContain('NEW_CURRENT');
    expect(replay.outputs).toContain('SAVED_PRESERVED');
    expect(replay.outputs.join('')).not.toMatch(/OLD_BEFORE_RESET|FORBIDDEN_OLD/);
  }
});
