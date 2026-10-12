import { expect, test } from '@playwright/test';

const novelId = process.env.QUEUE_AGENT_NOVEL_ID;
const taskId = process.env.QUEUE_AGENT_TASK_ID;
test.skip(!novelId || !taskId, '需要隔离 schema 的真实 Agent 保存结果');

test('独立工作和事件树交互使用真实 API，刷新后保持一致', async ({ page }) => {
  const failures: string[] = [];
  page.on('pageerror', error => failures.push(error.message));
  page.on('response', response => {
    if (response.url().includes('/api/') && response.status() >= 500) failures.push(`${response.status()} ${response.url()}`);
  });
  await page.setViewportSize({ width: 1440, height: 900 });
  for (let attempt = 0; attempt < 2; attempt++) {
    if (attempt) await page.reload();
    await page.goto(`/novels/${novelId}/event-trees?task_id=${taskId}`);
    await page.getByRole('region', { name: '整片事件森林' }).getByRole('button', { name: /拾得旧信/ }).click();
    await expect(page.getByRole('region', { name: '事件树结构' })).toBeVisible();
  }
  await page.screenshot({ path: test.info().outputPath('queue-agent-workspace.png'), fullPage: false });
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
