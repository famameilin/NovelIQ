import { useQuery, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useNovelTheme } from "@/hooks/useNovelTheme";
import { useNovelStore } from "@/store/novelStore";
import { DEFAULT_SEED, useThemeStore } from "@/store/themeStore";
import { getDiagnosis } from "@/api/results";

const getDiagnosisMock = vi.fn();

vi.mock("@/api/results", () => ({
  getDiagnosis: (...args: unknown[]) => getDiagnosisMock(...args),
}));

function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });
}

function ThemeHarness() {
  useNovelTheme();
  return null;
}

function DiagnosisConsumer() {
  const { currentNovelId, currentTaskId } = useNovelStore();

  useQuery({
    queryKey: ["results", currentNovelId, currentTaskId, "diagnosis"],
    queryFn: () => getDiagnosis(currentNovelId!, currentTaskId!),
    enabled: !!currentNovelId && !!currentTaskId,
    staleTime: 5 * 60 * 1000,
  });

  return null;
}

describe("useNovelTheme", () => {
  beforeEach(() => {
    getDiagnosisMock.mockReset();
    useNovelStore.setState({
      currentNovelId: "novel-1",
      currentTaskId: "task-1",
      novelsCache: [],
    });
    useThemeStore.setState({
      seedColor: DEFAULT_SEED,
      isDark: false,
      autoSyncEnabled: true,
    });
    document.documentElement.removeAttribute("style");
  });

  it("应复用 diagnosis 查询缓存而不是重复请求主题色", async () => {
    getDiagnosisMock.mockResolvedValue({
      theme_color: "#123456",
    });

    const queryClient = createQueryClient();

    render(
      <QueryClientProvider client={queryClient}>
        <ThemeHarness />
        <DiagnosisConsumer />
      </QueryClientProvider>,
    );

    await waitFor(() => {
      expect(getDiagnosisMock).toHaveBeenCalledTimes(1);
      expect(useThemeStore.getState().seedColor).toBe("#123456");
    });
  });

  it("禁用自动同步时不应把手动主题色覆盖回任务主题", async () => {
    getDiagnosisMock.mockResolvedValue({
      theme_color: "#123456",
    });

    useThemeStore.setState({
      seedColor: "#E84393",
      isDark: false,
      autoSyncEnabled: false,
    });

    const queryClient = createQueryClient();

    render(
      <QueryClientProvider client={queryClient}>
        <ThemeHarness />
      </QueryClientProvider>,
    );

    await waitFor(() => {
      expect(useThemeStore.getState().seedColor).toBe("#E84393");
      expect(getDiagnosisMock).not.toHaveBeenCalled();
    });
  });

  it("没有当前小说和任务时应恢复默认主题色", async () => {
    useNovelStore.setState({
      currentNovelId: null,
      currentTaskId: null,
      novelsCache: [],
    });
    useThemeStore.setState({
      seedColor: "#123456",
      isDark: false,
      autoSyncEnabled: true,
    });

    const queryClient = createQueryClient();

    render(
      <QueryClientProvider client={queryClient}>
        <ThemeHarness />
      </QueryClientProvider>,
    );

    await waitFor(() => {
      expect(useThemeStore.getState().seedColor).toBe(DEFAULT_SEED);
      expect(getDiagnosisMock).not.toHaveBeenCalled();
    });
  });
});
