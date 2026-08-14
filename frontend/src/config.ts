/**
 * 前端应用配置
 *
 * 与构建时环境变量（VITE_*）不同，这里的值写在源码中，
 * 修改后需重新部署前端，但不需要重新构建
 */

export const appConfig = {
  /**
   * 2026-04-30: 双模式 API/SSE 兼容
   * 改为同源优先，源码开发走 Vite `/api` 代理，Docker/Nginx 部署走同源反代
   */
  apiBaseUrl: typeof window !== "undefined" ? window.location.origin : "",

  /** 上传：单个文件最大字节数 */
  maxUploadSizeBytes: 10 * 1024 * 1024, // 10 MB 上限

  /** 上传：允许的文件扩展名 */
  acceptedFileTypes: [".txt"],

  /** 数据预加载：hover 后缓存的 staleTime（ms） */
  prefetchStaleTime: 5 * 60 * 1000, // 5 分钟

  /** LLM 输出缓冲区最大 chunk key 数量（LRU 上限） */
  maxLLMOutputKeys: 500,

  /** 单条 LLM 流在前端保留的最大字符数，避免后台恢复后把整页拖垮 */
  maxLLMOutputCharsPerGroup: 24_000,

  /** 单条 LLM 流在前端保留的最大行数，避免 Markdown 渲染窗口无限膨胀 */
  maxLLMOutputLinesPerGroup: 240,

  /** LLM 流式输出写入 store 的批量刷新间隔（ms） */
  llmOutputFlushIntervalMs: 120,

  /** 是否启用 MSW Mock API（仅开发模式生效，生产构建自动忽略） */
  enableMock: false,
} as const;
