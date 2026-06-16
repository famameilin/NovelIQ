import path from 'node:path'
import { fileURLToPath } from 'node:url'
import react, { reactCompilerPreset } from '@vitejs/plugin-react'
import babel from '@rolldown/plugin-babel'
import tailwindcss from '@tailwindcss/vite'
import { loadEnv } from 'vite'
import { configDefaults, defineConfig } from 'vitest/config'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

// Vite 配置文档：https://vite.dev/config/
/**
 * 2026-04-30: 双模式 API/SSE 兼容
 * 开发模式默认把 `/api` 代理到本机 8000 端口，生产环境继续优先走同源 `/api`
 */
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, __dirname, '')
  const backendProxyTarget = env.VITE_BACKEND_PROXY_TARGET || 'http://localhost:8000'

  return {
    plugins: [
      tailwindcss(),
      react(),
      babel({ presets: [reactCompilerPreset()] })
    ],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
      },
    },
    server: {
      proxy: {
        '/api': {
          target: backendProxyTarget,
          changeOrigin: true,
        },
      },
    },
    test: {
      environment: 'jsdom',
      // 2026-06-12: 默认单元测试排除 Playwright E2E 用例目录
      exclude: [...configDefaults.exclude, 'e2e/**'],
      setupFiles: './src/test/setup.ts',
    },
  }
})
