import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './styles/globals.css'
import App from './App.tsx'

/**
 * Mock 模式开关
 *
 * 启用方式（任选其一）：
 *   1. config.ts 中 enableMock 设为 true
 *   2. 构建时注入：VITE_ENABLE_MOCK=true npm run dev
 *   3. URL 参数：打开 http://localhost:5173/?mock=true
 *
 * 生产构建不会包含 mocks/ 目录的代码（tree-shaking），
 * 前提是 enableMock 为 false 且 VITE_ENABLE_MOCK 未设置。
 */
import { appConfig } from './config'

async function enableMocking() {
  if (
    import.meta.env.DEV && (
      appConfig.enableMock ||
      import.meta.env.VITE_ENABLE_MOCK === 'true' ||
      new URLSearchParams(window.location.search).get('mock') === 'true'
    )
  ) {
    const { worker } = await import('./mocks/browser');
    return worker.start({
      onUnhandledRequest: 'bypass',
      quiet: true,
    });
  }
}

enableMocking().then(() => {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
});
