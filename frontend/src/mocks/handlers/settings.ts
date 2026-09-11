/**
 * 设置模块 MSW handlers —— schema 驱动表单 + 用户设置 + 模型凭据
 *
 * mock 数据为契约代表性子集（字段结构与后端 /api/settings/* 一致），
 * 非 mock 模式下直连后端真实端点。
 */
import { HttpResponse, delay } from "msw";
import { http } from "msw";

const BASE = import.meta.env.VITE_API_BASE_URL || "";

const sections = [
  { id: "models", title: "模型参数", description: "标注/诊断任务与段落嵌入的运行参数", order: 1 },
  { id: "topic_model", title: "主题模型", description: "LDA 训练与主题变化候选参数", order: 2 },
  { id: "metrics", title: "指标计算", description: "各量化指标的阈值与采样参数", order: 3 },
  { id: "linguistic", title: "语言特征", description: "LTP 与 Word2Vec 能力开关及参数", order: 4 },
];

const fields = [
  {
    path: ["models", "annotation", "timeout_s"],
    field_type: "number",
    label: "标注超时（秒）",
    description: "",
    min_value: 1,
    max_value: null,
    step: null,
    enum_values: [],
    nullable: true,
    editable: true,
  },
  {
    path: ["models", "annotation", "temperature"],
    field_type: "number",
    label: "标注温度",
    description: "",
    min_value: 0,
    max_value: 2,
    step: 0.1,
    enum_values: [],
    nullable: false,
    editable: true,
  },
  {
    path: ["models", "annotation", "max_iterations"],
    field_type: "integer",
    label: "标注最大回合数",
    description: "",
    min_value: 1,
    max_value: null,
    step: null,
    enum_values: [],
    nullable: false,
    editable: true,
  },
  {
    path: ["models", "annotation", "allow_future_context"],
    field_type: "boolean",
    label: "允许读取未来文本",
    description: "",
    min_value: null,
    max_value: null,
    step: null,
    enum_values: [],
    nullable: false,
    editable: true,
  },
  {
    path: ["topic_model", "num_topics"],
    field_type: "integer",
    label: "主题数",
    description: "",
    min_value: 1,
    max_value: null,
    step: null,
    enum_values: [],
    nullable: false,
    editable: true,
  },
  {
    path: ["metrics", "mtld_threshold"],
    field_type: "number",
    label: "MTLD 阈值",
    description: "",
    min_value: 0,
    max_value: 1,
    step: null,
    enum_values: [],
    nullable: false,
    editable: true,
  },
  {
    path: ["linguistic", "word2vec", "enabled"],
    field_type: "boolean",
    label: "启用 Word2Vec",
    description: "",
    min_value: null,
    max_value: null,
    step: null,
    enum_values: [],
    nullable: false,
    editable: true,
  },
];

const values: Record<string, unknown> = {
  models: {
    annotation: {
      base_url: "https://api.example.com/v1",
      model: "text-model",
      api_key: "••••3456",
      timeout_s: 180,
      temperature: 0.7,
      max_iterations: 15,
      allow_future_context: true,
    },
    diagnosis: { api_key: "••••3456" },
    paragraph_embedding: {
      base_url: "http://localhost:8080/v1",
      model: "embedding-model",
      api_key: "••••abcd",
    },
  },
  topic_model: { num_topics: 25 },
  metrics: { mtld_threshold: 0.72 },
  linguistic: { ltp: { model_dir: "models/ltp/small" }, word2vec: { enabled: true } },
  logging: { console_level: "INFO" },
  paths: { results_dir: "outputs" },
};

const defaults: Record<string, unknown> = {
  models: {
    annotation: {
      base_url: null,
      model: null,
      api_key: null,
      timeout_s: null,
      temperature: 0.7,
      max_iterations: 10,
      allow_future_context: false,
    },
    diagnosis: { api_key: null },
    paragraph_embedding: { base_url: null, model: null, api_key: null },
  },
  topic_model: { num_topics: 25 },
  metrics: { mtld_threshold: 0.72 },
  linguistic: { ltp: { model_dir: null }, word2vec: { enabled: false } },
  logging: { console_level: "INFO" },
  paths: { results_dir: "outputs" },
};

const sources: Record<string, "default" | "file"> = {
  "models/annotation/timeout_s": "file",
  "models/annotation/temperature": "default",
  "models/annotation/max_iterations": "file",
  "models/annotation/allow_future_context": "file",
  "topic_model/num_topics": "default",
  "metrics/mtld_threshold": "default",
  "linguistic/word2vec/enabled": "file",
};

export const settingsSchemaHandler = http.get(`${BASE}/api/settings/schema`, async () => {
  await delay(200);
  return HttpResponse.json({ sections, fields });
});

export const settingsViewHandler = http.get(`${BASE}/api/settings`, async () => {
  await delay(200);
  return HttpResponse.json({ values, defaults, sources });
});

export const settingsUpdateHandler = http.put(`${BASE}/api/settings`, async () => {
  await delay(400);
  return HttpResponse.json({ values, defaults, sources });
});

export const settingsEnvHandler = http.put(`${BASE}/api/settings/env`, async () => {
  await delay(400);
  return HttpResponse.json({ values, defaults, sources });
});

export const settingsTestHandler = http.post(
  `${BASE}/api/settings/model-providers/:task/test`,
  async () => {
    await delay(600);
    return HttpResponse.json({ ok: true, latency_ms: 42.3, model_ids: ["mock-model"], error: null });
  }
);
