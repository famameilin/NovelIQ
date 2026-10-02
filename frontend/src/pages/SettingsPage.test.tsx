import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ModelEnvUpdate, SettingsSchemaResponse, SettingsViewResponse } from "@/api/types";
import { TooltipProvider } from "@/components/ui/tooltip";
import { SettingsPage } from "@/pages/SettingsPage";

const getSettingsSchemaMock = vi.fn();
const getSettingsMock = vi.fn();
const updateSettingsMock = vi.fn();
const updateModelEnvMock = vi.fn();
const testModelProviderMock = vi.fn();
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/api/settings", () => ({
  getSettingsSchema: (...args: unknown[]) => getSettingsSchemaMock(...args),
  getSettings: (...args: unknown[]) => getSettingsMock(...args),
  updateSettings: (...args: unknown[]) => updateSettingsMock(...args),
  updateModelEnv: (...args: unknown[]) => updateModelEnvMock(...args),
  testModelProvider: (...args: unknown[]) => testModelProviderMock(...args),
  settingsQueryKey: ["settings"],
}));

const schemaFixture: SettingsSchemaResponse = {
  sections: [
    { id: "models", title: "模型参数", description: "", order: 1 },
    { id: "metrics", title: "指标计算", description: "", order: 2 },
    { id: "topic_model", title: "主题模型", description: "", order: 3 },
  ],
  fields: [
    {
      path: ["models", "annotation", "timeout_s"], field_type: "number", label: "标注超时（秒）",
      description: "", min_value: 1, max_value: null, step: 1, enum_values: [], nullable: true, editable: true,
    },
    {
      path: ["metrics", "mtld_threshold"], field_type: "number", label: "MTLD 阈值",
      description: "", min_value: 0, max_value: 1, step: null, enum_values: [], nullable: false, editable: true,
    },
    {
      path: ["topic_model", "num_topics"], field_type: "integer", label: "主题数",
      description: "", min_value: 1, max_value: null, step: 1, enum_values: [], nullable: false, editable: true,
    },
  ],
};
const viewFixture: SettingsViewResponse = {
  values: {
    models: {
      model_pool: [
        { model_id: "text-model", base_url: "https://first.example/v1", api_key: "••••3456", weight: 1, max_in_flight: 8,
          temperature: 0.7, top_p: 0.8, max_tokens: 131072 },
        { model_id: "second-model", base_url: "https://second.example/v1", api_key: "••••7890", weight: 3, max_in_flight: 2,
          temperature: 0.3, top_p: 0.9, max_tokens: 4096 },
      ],
      diagnosis_model_id: "second-model",
      annotation: { timeout_s: 100 },
      diagnosis: {},
      paragraph_embedding: { base_url: "http://localhost:8080/v1", model: "emb", api_key: "••••abcd" },
    },
    metrics: { mtld_threshold: 0.72 },
    topic_model: { num_topics: 24 },
  },
  defaults: {
    models: {
      model_pool: [], diagnosis_model_id: null,
      annotation: { timeout_s: null }, diagnosis: {},
      paragraph_embedding: { base_url: null, model: null, api_key: null },
    },
    metrics: { mtld_threshold: 0.72 },
    topic_model: { num_topics: 25 },
  },
  sources: { "topic_model/num_topics": "file", "metrics/mtld_threshold": "default" },
};

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>
    <TooltipProvider><SettingsPage /></TooltipProvider>
  </QueryClientProvider>);
}

async function editModel(modelId = "text-model") {
  await userEvent.click(screen.getByRole("button", { name: `编辑模型：${modelId}` }));
  return within(screen.getByRole("dialog"));
}

beforeEach(() => {
  vi.clearAllMocks();
  getSettingsSchemaMock.mockResolvedValue(schemaFixture);
  getSettingsMock.mockResolvedValue(structuredClone(viewFixture));
  updateSettingsMock.mockResolvedValue(structuredClone(viewFixture));
  updateModelEnvMock.mockImplementation(async (patch: ModelEnvUpdate) => {
    const view = structuredClone(viewFixture);
    const models = view.values.models as Record<string, unknown>;
    if (patch.model_pool) models.model_pool = patch.model_pool.map((entry) => ({
      model_id: entry.model_id, base_url: entry.base_url, weight: entry.weight,
      max_in_flight: entry.max_in_flight, temperature: entry.temperature, top_p: entry.top_p,
      max_tokens: entry.max_tokens, api_key: "••••saved",
    }));
    if ("diagnosis_model_id" in patch) models.diagnosis_model_id = patch.diagnosis_model_id;
    return view;
  });
  testModelProviderMock.mockResolvedValue({ ok: true, latency_ms: 42, model_ids: ["m"], error: null });
});

describe("SettingsPage", () => {
  it("显示统一模型池及诊断选择，不显示文本连接和额外分类", async () => {
    renderPage();
    expect(await screen.findByRole("region", { name: "模型池" })).toBeInTheDocument();
    expect(screen.getByText("模型参数")).toBeInTheDocument();
    expect(screen.getByText("MTLD 阈值")).toBeInTheDocument();
    expect(screen.getByText("25.0%")).toBeInTheDocument();
    expect(screen.getByText("75.0%")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "指定诊断模型" })).toHaveTextContent("second-model");
    expect(screen.queryByText(/文本服务连接|标注模型池|独立诊断模型|连续性|供应方顺序|质量监控|人工复核|Worker|RPM|TPM|投影槽位|全局槽位/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "添加供应方" })).not.toBeInTheDocument();
  });

  it("编辑显示八个字段，采样参数随模型回显", async () => {
    renderPage();
    await screen.findByRole("region", { name: "模型池" });
    const dialog = await editModel("second-model");
    expect(dialog.getByLabelText("URL")).toHaveValue("https://second.example/v1");
    expect(dialog.getByLabelText("ID")).toHaveValue("second-model");
    expect(dialog.getByLabelText("权重")).toHaveValue(3);
    expect(dialog.getByLabelText("并发")).toHaveValue(2);
    expect(dialog.getByLabelText("温度")).toHaveValue(0.3);
    expect(dialog.getByLabelText("top_p")).toHaveValue(0.9);
    expect(dialog.getByLabelText("输出 Token 上限")).toHaveValue(4096);
    expect(dialog.getByLabelText("Key")).toHaveValue("");
    expect(dialog.getByLabelText("Key")).toHaveAttribute("placeholder", "已配置（••••7890），留空不修改");
  });

  it("极大但有限的权重仍显示正确占比", async () => {
    const view = structuredClone(viewFixture);
    const models = view.values.models as { model_pool: { weight: number }[] };
    for (const entry of models.model_pool) entry.weight = Number.MAX_VALUE;
    getSettingsMock.mockResolvedValue(view);
    renderPage();
    await screen.findByRole("region", { name: "模型池" });
    expect(screen.getAllByText("50.0%")).toHaveLength(2);
  });

  it("新增模型校验八个字段并通过环境接口保存", async () => {
    renderPage();
    await screen.findByRole("region", { name: "模型池" });
    await userEvent.click(screen.getByRole("button", { name: "新增模型" }));
    const dialog = within(screen.getByRole("dialog"));
    await userEvent.click(dialog.getByRole("button", { name: "添加" }));
    expect(dialog.getByRole("alert")).toHaveTextContent("模型 ID 不能为空");
    fireEvent.change(dialog.getByLabelText("ID"), { target: { value: "text-model" } });
    await userEvent.click(dialog.getByRole("button", { name: "添加" }));
    expect(dialog.getByRole("alert")).toHaveTextContent("模型 ID 已存在");
    fireEvent.change(dialog.getByLabelText("ID"), { target: { value: "new-model" } });
    fireEvent.change(dialog.getByLabelText("URL"), { target: { value: "https://new.example/v1" } });
    fireEvent.change(dialog.getByLabelText("Key"), { target: { value: "sk-new-key" } });
    fireEvent.change(dialog.getByLabelText("权重"), { target: { value: "2" } });
    fireEvent.change(dialog.getByLabelText("并发"), { target: { value: "4" } });
    fireEvent.change(dialog.getByLabelText("温度"), { target: { value: "0.3" } });
    fireEvent.change(dialog.getByLabelText("top_p"), { target: { value: "0.9" } });
    fireEvent.change(dialog.getByLabelText("输出 Token 上限"), { target: { value: "4096" } });
    await userEvent.click(dialog.getByRole("button", { name: "添加" }));
    await userEvent.click(screen.getByRole("button", { name: "保存模型池" }));
    await waitFor(() => expect(updateModelEnvMock).toHaveBeenCalledWith({
      model_pool: expect.arrayContaining([{ model_id: "new-model", base_url: "https://new.example/v1", api_key: "sk-new-key",
        weight: 2, max_in_flight: 4, temperature: 0.3, top_p: 0.9, max_tokens: 4096 }]),
      diagnosis_model_id: "second-model",
    }));
    expect(updateSettingsMock).not.toHaveBeenCalled();
  });

  it("新增模型采样参数越界被拒绝", async () => {
    renderPage();
    await screen.findByRole("region", { name: "模型池" });
    await userEvent.click(screen.getByRole("button", { name: "新增模型" }));
    const dialog = within(screen.getByRole("dialog"));
    fireEvent.change(dialog.getByLabelText("ID"), { target: { value: "new-model" } });
    fireEvent.change(dialog.getByLabelText("URL"), { target: { value: "https://new.example/v1" } });
    fireEvent.change(dialog.getByLabelText("Key"), { target: { value: "sk-new-key" } });
    fireEvent.change(dialog.getByLabelText("温度"), { target: { value: "2.5" } });
    await userEvent.click(dialog.getByRole("button", { name: "添加" }));
    expect(dialog.getByRole("alert")).toHaveTextContent("温度必须是 [0, 2] 内的数值");
    fireEvent.change(dialog.getByLabelText("温度"), { target: { value: "0.5" } });
    fireEvent.change(dialog.getByLabelText("top_p"), { target: { value: "1.5" } });
    await userEvent.click(dialog.getByRole("button", { name: "添加" }));
    expect(dialog.getByRole("alert")).toHaveTextContent("top_p 必须在 [0, 1] 内");
    fireEvent.change(dialog.getByLabelText("top_p"), { target: { value: "0.9" } });
    fireEvent.change(dialog.getByLabelText("输出 Token 上限"), { target: { value: "0" } });
    await userEvent.click(dialog.getByRole("button", { name: "添加" }));
    expect(dialog.getByRole("alert")).toHaveTextContent("输出 Token 上限必须是正整数");
  });

  it("编辑修改地址、ID和并发，留空 Key 不覆盖已保存值", async () => {
    renderPage();
    await screen.findByRole("region", { name: "模型池" });
    const dialog = await editModel();
    fireEvent.change(dialog.getByLabelText("URL"), { target: { value: "https://changed.example/v1" } });
    fireEvent.change(dialog.getByLabelText("ID"), { target: { value: "renamed-model" } });
    fireEvent.change(dialog.getByLabelText("并发"), { target: { value: "5" } });
    await userEvent.click(dialog.getByRole("button", { name: "应用修改" }));
    await userEvent.click(screen.getByRole("button", { name: "保存模型池" }));
    await waitFor(() => expect(updateModelEnvMock).toHaveBeenCalledWith({
      model_pool: expect.arrayContaining([{ model_id: "renamed-model", original_model_id: "text-model",
        base_url: "https://changed.example/v1", weight: 1, max_in_flight: 5,
        temperature: 0.7, top_p: 0.8, max_tokens: 131072 }]), diagnosis_model_id: "second-model",
    }));
    expect(JSON.stringify(updateModelEnvMock.mock.calls)).not.toContain("••••");
  });

  it("测试连接可以使用草稿 Key，但不保存", async () => {
    renderPage();
    await screen.findByRole("region", { name: "模型池" });
    const dialog = await editModel();
    fireEvent.change(dialog.getByLabelText("Key"), { target: { value: "sk-draft" } });
    await userEvent.click(dialog.getByRole("button", { name: "测试连接" }));
    await waitFor(() => expect(testModelProviderMock).toHaveBeenCalledWith("pool", {
      base_url: "https://first.example/v1", model_id: "text-model", api_key: "sk-draft",
    }));
    expect(updateModelEnvMock).not.toHaveBeenCalled();
  });

  it("指定诊断模型从池内选择并保存", async () => {
    renderPage();
    await screen.findByRole("region", { name: "模型池" });
    fireEvent.keyDown(screen.getByRole("combobox", { name: "指定诊断模型" }), { key: "ArrowDown" });
    await userEvent.click(screen.getByRole("option", { name: "text-model" }));
    await userEvent.click(screen.getByRole("button", { name: "保存模型池" }));
    await waitFor(() => expect(updateModelEnvMock).toHaveBeenCalledWith(expect.objectContaining({ diagnosis_model_id: "text-model" })));
    expect(updateSettingsMock).not.toHaveBeenCalled();
  });

  it("诊断模型改名同步选项，删除后清除指定", async () => {
    renderPage();
    await screen.findByRole("region", { name: "模型池" });
    const dialog = await editModel("second-model");
    fireEvent.change(dialog.getByLabelText("ID"), { target: { value: "renamed-diagnostic" } });
    await userEvent.click(dialog.getByRole("button", { name: "应用修改" }));
    expect(screen.getByRole("combobox", { name: "指定诊断模型" })).toHaveTextContent("renamed-diagnostic");
    await userEvent.click(screen.getByRole("button", { name: "删除模型：renamed-diagnostic" }));
    expect(screen.getByRole("combobox", { name: "指定诊断模型" })).toHaveTextContent("未指定");
    expect(screen.getByRole("button", { name: "删除模型：text-model" })).toBeDisabled();
  });

  it("所有权重为零禁止保存，放弃池修改可恢复", async () => {
    renderPage();
    await screen.findByRole("region", { name: "模型池" });
    for (const modelId of ["text-model", "second-model"]) {
      const dialog = await editModel(modelId);
      fireEvent.change(dialog.getByLabelText("权重"), { target: { value: "0" } });
      await userEvent.click(dialog.getByRole("button", { name: "应用修改" }));
    }
    expect(screen.getByRole("alert")).toHaveTextContent("至少一个模型的权重必须大于零");
    expect(screen.getByRole("button", { name: "保存模型池" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "放弃模型池修改" }));
    expect(screen.getByText("25.0%")).toBeInTheDocument();
    expect(screen.getByText("75.0%")).toBeInTheDocument();
  });

  it("参数单独保存不提交连接或模型池", async () => {
    renderPage();
    await screen.findByRole("region", { name: "模型池" });
    fireEvent.change(screen.getByLabelText("主题数"), { target: { value: "30" } });
    await userEvent.click(screen.getByRole("button", { name: "保存设置" }));
    await waitFor(() => expect(updateSettingsMock).toHaveBeenCalledWith({ topic_model: { num_topics: 30 } }));
  });

  it("模型池保存不覆盖未保存参数草稿", async () => {
    renderPage();
    await screen.findByRole("region", { name: "模型池" });
    fireEvent.change(screen.getByLabelText("主题数"), { target: { value: "30" } });
    const dialog = await editModel();
    fireEvent.change(dialog.getByLabelText("权重"), { target: { value: "4" } });
    await userEvent.click(dialog.getByRole("button", { name: "应用修改" }));
    await userEvent.click(screen.getByRole("button", { name: "保存模型池" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "保存模型池" })).toBeDisabled());
    expect(screen.getByLabelText("主题数")).toHaveValue(30);
    await userEvent.click(screen.getByRole("button", { name: "保存设置" }));
    await waitFor(() => expect(updateSettingsMock).toHaveBeenCalledWith({ topic_model: { num_topics: 30 } }));
  });

  it("参数放弃和恢复默认保持既有行为", async () => {
    renderPage();
    await screen.findByRole("region", { name: "模型池" });
    expect(screen.getByRole("button", { name: "保存设置" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("主题数"), { target: { value: "32" } });
    await userEvent.click(screen.getByRole("button", { name: "放弃修改" }));
    expect(screen.getByLabelText("主题数")).toHaveValue(24);
    await userEvent.click(screen.getByRole("button", { name: "恢复默认：主题数" }));
    await userEvent.click(screen.getByRole("button", { name: "保存设置" }));
    await waitFor(() => expect(updateSettingsMock).toHaveBeenCalledWith({ topic_model: { num_topics: 25 } }));
  });

  it("未限制默认值恢复为 null", async () => {
    renderPage();
    await screen.findByRole("region", { name: "模型池" });
    await userEvent.click(screen.getByRole("button", { name: "恢复默认：标注超时（秒）" }));
    expect(screen.getByLabelText("标注超时（秒）")).toHaveValue(null);
    await userEvent.click(screen.getByRole("button", { name: "保存设置" }));
    await waitFor(() => expect(updateSettingsMock).toHaveBeenCalledWith({ models: { annotation: { timeout_s: null } } }));
  });

  it("嵌入模型凭据仍可单独编辑", async () => {
    renderPage();
    await screen.findByRole("region", { name: "模型池" });
    const embedding = within(screen.getByRole("region", { name: "嵌入模型" }));
    fireEvent.change(embedding.getByLabelText("Base URL"), { target: { value: "http://localhost:9090/v1" } });
    await userEvent.click(embedding.getByRole("button", { name: "保存凭据" }));
    await waitFor(() => expect(updateModelEnvMock).toHaveBeenCalledWith({ embedding_model: {
      base_url: "http://localhost:9090/v1", model: "emb", api_key: null,
    } }));
  });
});
