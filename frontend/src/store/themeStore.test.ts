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

  it("latest-only 配置下应只保留默认版本值且不再声明 migrate 兼容逻辑", () => {
    const options = useThemeStore.persist.getOptions();

    expect(options.version).toBe(0);
    expect(options.migrate).toBeUndefined();
  });
});
