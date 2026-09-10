/**
 * 设置模块 API —— schema 驱动表单 + 用户设置保存 + 模型凭据（.env 单源编辑）
 */
import { apiClient } from "./client";
import type {
  ModelEnvUpdate,
  ModelProviderTestResponse,
  SettingsSchemaResponse,
  SettingsViewResponse,
} from "./types";

/** 字段注册表：前端按此自动渲染分区表单 */
export async function getSettingsSchema(): Promise<SettingsSchemaResponse> {
  const { data } = await apiClient.get<SettingsSchemaResponse>("/api/settings/schema");
  return data;
}

/** 生效值（api_key 打码）+ 代码默认值 + 逐字段来源 */
export async function getSettings(): Promise<SettingsViewResponse> {
  const { data } = await apiClient.get<SettingsViewResponse>("/api/settings");
  return data;
}

/** 保存用户设置（支持部分提交，后端深合并后稀疏化写回 settings.json 并热生效） */
export async function updateSettings(values: Record<string, unknown>): Promise<SettingsViewResponse> {
  const { data } = await apiClient.put<SettingsViewResponse>("/api/settings", { values });
  return data;
}

/** 模型凭据更新（写 .env 白名单键 + 进程热生效；api_key 留空=不修改） */
export async function updateModelEnv(payload: ModelEnvUpdate): Promise<SettingsViewResponse> {
  const { data } = await apiClient.put<SettingsViewResponse>("/api/settings/env", payload);
  return data;
}

/** 测试模型服务连通性（字段缺省用当前生效配置） */
export async function testModelProvider(
  task: "annotation" | "embedding",
  payload?: { base_url?: string; api_key?: string }
): Promise<ModelProviderTestResponse> {
  const { data } = await apiClient.post<ModelProviderTestResponse>(
    `/api/settings/model-providers/${task}/test`,
    payload ?? {}
  );
  return data;
}

export const settingsQueryKey = ["settings"] as const;
