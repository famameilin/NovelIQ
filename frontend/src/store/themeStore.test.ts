import { describe, expect, it } from "vitest";

import { useThemeStore } from "@/store/themeStore";

describe("themeStore 持久化配置", () => {
  it("自动同步开启时不应持久化任务派生的主题色", () => {
    const partialize = useThemeStore.persist.getOptions().partialize;
    const persisted = partialize?.({
      ...useThemeStore.getState(),
      seedColor: "#123456",
      isDark: true,
      autoSyncEnabled: true,
    });

    expect(persisted).toEqual({
      isDark: true,
      autoSyncEnabled: true,
    });
  });

  it("自动同步关闭时应保留手动选择的主题色", () => {
    const partialize = useThemeStore.persist.getOptions().partialize;
    const persisted = partialize?.({
      ...useThemeStore.getState(),
      seedColor: "#123456",
      isDark: false,
      autoSyncEnabled: false,
    });

    expect(persisted).toEqual({
      seedColor: "#123456",
      isDark: false,
      autoSyncEnabled: false,
    });
  });
});
