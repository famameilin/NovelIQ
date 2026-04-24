import { useQuery, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { useNovelTheme } from "@/hooks/useNovelTheme";
import { useNovelStore } from "@/store/novelStore";
import { DEFAULT_SEED, useThemeStore } from "@/store/themeStore";
import { getDiagnosis } from "@/api/results";
import { generateHomeThemePalette, generateThemePalette } from "@/lib/theme";

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

function renderThemeHarness(queryClient: QueryClient, route: string, withDiagnosisConsumer = false) {
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[route]}>
        <Routes>
          <Route
            path="*"
            element={
              <>
                <ThemeHarness />
                {withDiagnosisConsumer ? <DiagnosisConsumer /> : null}
              </>
            }
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
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

    renderThemeHarness(queryClient, "/novels/novel-1?task_id=task-1", true);

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

    renderThemeHarness(queryClient, "/dev/components");

    await waitFor(() => {
      expect(useThemeStore.getState().seedColor).toBe("#E84393");
      expect(getDiagnosisMock).not.toHaveBeenCalled();
    });
  });

  it("业务页即使残留自动同步关闭标记也应跟随任务主题更新", async () => {
    getDiagnosisMock.mockResolvedValue({
      theme_color: "#123456",
    });
    useThemeStore.setState({
      seedColor: DEFAULT_SEED,
      isDark: false,
      autoSyncEnabled: false,
    });

    const queryClient = createQueryClient();

    renderThemeHarness(queryClient, "/novels/novel-1?task_id=task-1");

    await waitFor(() => {
      expect(getDiagnosisMock).toHaveBeenCalledTimes(1);
      expect(useThemeStore.getState().seedColor).toBe("#123456");
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

    renderThemeHarness(queryClient, "/");

    await waitFor(() => {
      expect(getDiagnosisMock).not.toHaveBeenCalled();
      expect(document.documentElement.style.getPropertyValue("--background")).toBe("0 0% 100%");
      expect(document.documentElement.style.getPropertyValue("--primary")).toBe("239 84% 50%");
    });
  });

  it("首页路由即使残留旧主题色也应强制切到首页品牌色", async () => {
    useNovelStore.setState({
      currentNovelId: null,
      currentTaskId: null,
      novelsCache: [],
    });
    useThemeStore.setState({
      seedColor: "#123456",
      isDark: false,
      autoSyncEnabled: false,
    });

    const queryClient = createQueryClient();

    renderThemeHarness(queryClient, "/");

    await waitFor(() => {
      expect(getDiagnosisMock).not.toHaveBeenCalled();
      expect(document.documentElement.style.getPropertyValue("--surface")).toBe("0 0% 100%");
      expect(document.documentElement.style.getPropertyValue("--text-on-primary")).toBe("0 0% 100%");
      expect(document.documentElement.style.getPropertyValue("--chart-2")).toBe("279 74% 55%");
    });
  });

  it("小说详情页未选择任务时应保持白底预备态，不提前吃旧任务主题", async () => {
    useNovelStore.setState({
      currentNovelId: "novel-1",
      currentTaskId: "task-old",
      novelsCache: [],
    });
    useThemeStore.setState({
      seedColor: "#123456",
      isDark: false,
      autoSyncEnabled: true,
    });

    const queryClient = createQueryClient();

    renderThemeHarness(queryClient, "/novels/novel-1");

    await waitFor(() => {
      expect(getDiagnosisMock).not.toHaveBeenCalled();
      expect(document.documentElement.style.getPropertyValue("--background")).toBe("0 0% 100%");
      expect(document.documentElement.style.getPropertyValue("--primary")).toBe("239 84% 50%");
    });
  });

  it("新任务主题未返回前应保持中性白底，而不是切到默认紫色主题", async () => {
    let resolveDiagnosis!: (value: { theme_color: string }) => void;
    getDiagnosisMock.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveDiagnosis = resolve;
        }),
    );
    useNovelStore.setState({
      currentNovelId: "novel-1",
      currentTaskId: "task-2",
      novelsCache: [],
    });
    useThemeStore.setState({
      seedColor: "#FFFFFF",
      isDark: false,
      autoSyncEnabled: true,
    });

    const queryClient = createQueryClient();

    renderThemeHarness(queryClient, "/novels/novel-1?task_id=task-2");

    await waitFor(() => {
      expect(getDiagnosisMock).toHaveBeenCalledTimes(1);
    });

    const neutralPalette = generateHomeThemePalette();
    expect(document.documentElement.style.getPropertyValue("--primary")).toBe(neutralPalette.light["--primary"]);
    expect(document.documentElement.style.getPropertyValue("--background")).toBe(
      neutralPalette.light["--background"],
    );

    resolveDiagnosis({ theme_color: "#123456" });

    await waitFor(() => {
      expect(useThemeStore.getState().seedColor).toBe("#123456");
      expect(document.documentElement.style.getPropertyValue("--primary")).toBe(
        generateThemePalette("#123456").light["--primary"],
      );
    });
  });

  it("新任务诊断暂不可用时应保持中性白底并清掉旧 seed", async () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    getDiagnosisMock.mockRejectedValue(new Error("diagnosis not ready"));
    useNovelStore.setState({
      currentNovelId: "novel-1",
      currentTaskId: "task-running",
      novelsCache: [],
    });
    useThemeStore.setState({
      seedColor: "#E84393",
      isDark: false,
      autoSyncEnabled: true,
    });

    const queryClient = createQueryClient();

    renderThemeHarness(queryClient, "/novels/novel-1?task_id=task-running");

    const neutralPalette = generateHomeThemePalette();
    await waitFor(() => {
      expect(useThemeStore.getState().seedColor).toBe(DEFAULT_SEED);
      expect(document.documentElement.style.getPropertyValue("--background")).toBe(
        neutralPalette.light["--background"],
      );
      expect(document.documentElement.style.getPropertyValue("--surface")).toBe(
        neutralPalette.light["--surface"],
      );
    });

    expect(warnSpy).toHaveBeenCalled();
    warnSpy.mockRestore();
  });

  it("组件展示页首屏不应发起任务主题同步或覆盖手动试色", async () => {
    useThemeStore.setState({
      seedColor: "#E84393",
      isDark: false,
      autoSyncEnabled: true,
    });

    const queryClient = createQueryClient();

    renderThemeHarness(queryClient, "/dev/components");

    await waitFor(() => {
      expect(getDiagnosisMock).not.toHaveBeenCalled();
      expect(useThemeStore.getState().seedColor).toBe("#E84393");
      expect(document.documentElement.style.getPropertyValue("--primary")).toBe(
        generateThemePalette("#E84393").light["--primary"],
      );
    });
  });
});
