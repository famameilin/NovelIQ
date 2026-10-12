import axios from "axios";
import { afterEach, expect, it, vi } from "vitest";
import { apiClient } from "./client";

afterEach(() => vi.restoreAllMocks());

it("搜索取消仍向调用方拒绝，但不记录为网络连接失败", async () => {
  const log = vi.spyOn(console, "error").mockImplementation(() => {});
  const request = apiClient.get("/cancelled-search", { adapter: config => {
    const error = new axios.CanceledError("canceled");
    error.config = config;
    error.request = {};
    return Promise.reject(error);
  } });
  await expect(request).rejects.toMatchObject({ code: "ERR_CANCELED" });
  expect(log).not.toHaveBeenCalled();
});

it("真实网络连接失败继续记录并传回原始错误", async () => {
  const log = vi.spyOn(console, "error").mockImplementation(() => {});
  const request = apiClient.get("/network-failure", { adapter: config => Promise.reject(new axios.AxiosError("Network Error", "ERR_NETWORK", config, {})) });
  await expect(request).rejects.toMatchObject({ code: "ERR_NETWORK" });
  expect(log).toHaveBeenCalledWith("[API Error] 无法连接到服务器");
});
