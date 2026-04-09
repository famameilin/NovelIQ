import axios from "axios";
import { appConfig } from "@/config";

export const apiClient = axios.create({
  baseURL: appConfig.apiBaseUrl,
  timeout: 30000,
  headers: {
    "Content-Type": "application/json",
  },
});

// Response interceptor for unified error handling
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response) {
      const detail = error.response.data?.detail || "请求失败";
      console.error(`[API Error] ${error.response.status}: ${detail}`);
    } else if (error.request) {
      console.error("[API Error] 无法连接到服务器");
    } else {
      console.error("[API Error]", error.message);
    }
    return Promise.reject(error);
  }
);
