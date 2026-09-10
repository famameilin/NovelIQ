import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SettingsPage } from "@/pages/SettingsPage";
import type { SettingsSchemaResponse, SettingsViewResponse } from "@/api/types";

const getSettingsSchemaMock = vi.fn();
const getSettingsMock = vi.fn();
const updateSettingsMock = vi.fn();
const updateModelEnvMock = vi.fn();
const testModelProviderMock = vi.fn();

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/api/settings", () => ({
  getSettingsSchema: (...args: unknown[]) => getSettingsSchemaMock(...args),
  getSettings: (...args: unknown[]) => getSettingsMock(...args),
  updateSettings: (...args: unknown[]) => updateSettingsMock(...args),
  updateModelEnv: (...args: unknown[]) => updateModelEnvMock(...args),
  testModelProvider: (...args: unknown[]) => testModelProviderMock(...args),
  settingsQueryKey: ["settings"],
}));

/** 测试断言用：从嵌套 JSON 中按路径取值（契约是 Record<string, unknown> 树） */
function at(root: unknown, path: string[]): unknown {
  let current: unknown = root;
  for (const segment of path) {
    if (typeof current !== "object" || current === null) return undefined;
    current = (current as Record<string, unknown>)[segment];
  }
  return current;
}

const schemaFixture: SettingsSchemaResponse = {
  sections: [
    { id: "models", title: "模型参数", description: "运行参数", order: 1 },
    { id: "metrics", title: "指标计算", description: "阈值", order: 2 },
  ],
  fields: [
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
  ],
};

const viewFixture: SettingsViewResponse = {
  values: {
    models: {
      annotation: { base_url: "https://api.example.com/v1", model: "text-model", api_key: "••••3456", temperature: 0.9 },
      diagnosis: {},
      paragraph_embedding: { base_url: "http://localhost:8080/v1", model: "emb", api_key: "••••abcd" },
    },
    metrics: { mtld_threshold: 0.72 },
  },
  defaults: {
    models: {
      annotation: { base_url: null, model: null, api_key: null, temperature: 0.7 },
      diagnosis: {},
      paragraph_embedding: { base_url: null, model: null, api_key: null },
    },
    metrics: { mtld_threshold: 0.72 },
  },
  sources: { "models/annotation/temperature": "file", "metrics/mtld_threshold": "default" },
};

function createQueryClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function renderPage() {
  return render(
    <QueryClientProvider client={createQueryClient()}>
      <SettingsPage />
    </QueryClientProvider>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  getSettingsSchemaMock.mockResolvedValue(schemaFixture);
  getSettingsMock.mockResolvedValue(deepCloneFixture(viewFixture));
  updateSettingsMock.mockResolvedValue(deepCloneFixture(viewFixture));
  updateModelEnvMock.mockResolvedValue(deepCloneFixture(viewFixture));
  testModelProviderMock.mockResolvedValue({ ok: true, latency_ms: 42, model_ids: ["m"], error: null });
});

function deepCloneFixture<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

describe("SettingsPage", () => {
  it("渲染分区表单与字段", async () => {
    renderPage();
    expect(await screen.findByText("文本模型（标注 / 诊断）")).toBeInTheDocument();
    expect(screen.getByText("模型参数")).toBeInTheDocument();
    expect(screen.getByText("标注温度")).toBeInTheDocument();
    expect(screen.getByText("MTLD 阈值")).toBeInTheDocument();
  });

  it("api_key 以打码值提示且输入框为空", async () => {
    renderPage();
    await screen.findByText("文本模型（标注 / 诊断）");
    const keyInput = screen.getByPlaceholderText(/已配置（••••3456）, 留空不修改|已配置（••••3456），留空不修改/);
    expect(keyInput).toHaveValue("");
  });

  it("编辑后保存调用 updateSettings 并携带修改值", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("文本模型（标注 / 诊断）");

    await user.click(screen.getByRole("button", { name: "编辑参数" }));
    // number input 逐字符 type 会与受控值互相干扰，用 fireEvent 整值提交
    fireEvent.change(screen.getByDisplayValue("0.9"), { target: { value: "1.2" } });
    await user.click(screen.getByRole("button", { name: "保存设置" }));

    await waitFor(() => expect(updateSettingsMock).toHaveBeenCalledTimes(1));
    expect(at(updateSettingsMock.mock.calls[0][0], ["models", "annotation", "temperature"])).toBe(1.2);
  });

  it("恢复默认按钮把字段值回退为代码默认", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("文本模型（标注 / 诊断）");

    await user.click(screen.getByRole("button", { name: "编辑参数" }));
    await user.click(screen.getByRole("button", { name: "恢复默认：标注温度" }));
    await user.click(screen.getByRole("button", { name: "保存设置" }));

    await waitFor(() => expect(updateSettingsMock).toHaveBeenCalledTimes(1));
    expect(at(updateSettingsMock.mock.calls[0][0], ["models", "annotation", "temperature"])).toBe(0.7);
  });

  it("凭据保存 api_key 留空表示不修改", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("文本模型（标注 / 诊断）");

    await user.click(screen.getAllByRole("button", { name: "保存凭据" })[0]);
    await waitFor(() => expect(updateModelEnvMock).toHaveBeenCalledTimes(1));
    const payload = updateModelEnvMock.mock.calls[0][0] as Record<string, unknown>;
    expect(at(payload, ["model", "api_key"])).toBeNull();
    expect(at(payload, ["model", "base_url"])).toBe("https://api.example.com/v1");
  });

  it("测试连接按钮调用 testModelProvider", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("文本模型（标注 / 诊断）");

    await user.click(screen.getAllByRole("button", { name: /测试连接/ })[0]);
    await waitFor(() => expect(testModelProviderMock).toHaveBeenCalledTimes(1));
    expect(testModelProviderMock.mock.calls[0][0]).toBe("annotation");
  });
});
