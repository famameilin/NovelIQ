import { describe, expect, it } from "vitest";

import { useThemeStore } from "@/store/themeStore";

describe("themeStore 持久化配置", () => {
  it("自动同步开启时不应持久化任务派生的主题色和临时同步开关", () => {
    const partialize = useThemeStore.persist.getOptions().partialize;
    const persisted = partialize?.({
      ...useThemeStore.getState(),
      seedColor: "#123456",
      isDark: true,
      autoSyncEnabled: true,
    });

    expect(persisted).toEqual({
      isDark: true,
    });
  });

  it("自动同步关闭时应只保留手动选择的主题色", () => {
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
    });
  });

  it("迁移旧持久化数据时应清掉自动同步模式下残留的 seedColor", async () => {
    const migrate = useThemeStore.persist.getOptions().migrate;
    const migrated = await migrate?.({
      seedColor: "#123456",
      isDark: true,
      autoSyncEnabled: true,
    });

    expect(migrated).toEqual({
      isDark: true,
      autoSyncEnabled: true,
    });
  });

  it("迁移旧持久化数据时应把旧的自动同步关闭状态恢复为默认开启", async () => {
    const migrate = useThemeStore.persist.getOptions().migrate;
    const migrated = await migrate?.({
      seedColor: "#123456",
      isDark: false,
      autoSyncEnabled: false,
    });

    expect(migrated).toEqual({
      seedColor: "#123456",
      isDark: false,
      autoSyncEnabled: true,
    });
  });
});
