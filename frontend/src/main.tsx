import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './styles/globals.css'
import App from './App.tsx'

// 开发环境下按配置或 URL 参数启用 mock
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
