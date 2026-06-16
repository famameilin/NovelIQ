/**
 * 创建时间: 2026-05-30
 * 任务: Playwright E2E测试配置
 * 说明: Playwright端到端测试配置，使用chromium浏览器，baseURL指向Vite开发服务器
 */
import { defineConfig, devices } from '@playwright/test';

// 2026-06-12: 固定 E2E 端口，避免复用其他项目的 5173 服务
const e2ePort = process.env.E2E_PORT ?? '5176';
const e2eBaseURL = `http://127.0.0.1:${e2ePort}`;

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: 'html',
  use: {
    baseURL: e2eBaseURL,
    trace: 'on-first-retry',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: {
    command: `npm run dev -- --host 127.0.0.1 --port ${e2ePort} --strictPort`,
    url: e2eBaseURL,
    reuseExistingServer: !process.env.CI,
    timeout: 30000,
  },
});
