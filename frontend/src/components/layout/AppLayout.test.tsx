import { render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { AppLayout } from "@/components/layout/AppLayout";
import { useNovelStore } from "@/store/novelStore";

vi.mock("@/components/layout/TopBar", () => ({
  TopBar: () => <div data-testid="top-bar" />,
}));

vi.mock("@/components/layout/HeroPanel", () => ({
  HeroPanel: () => <div data-testid="hero-panel" />,
}));

vi.mock("@/components/layout/SideNav", () => ({
  SideNav: () => <div data-testid="side-nav" />,
}));

describe("AppLayout", () => {
  beforeEach(() => {
    useNovelStore.setState({
      currentNovelId: "novel-1",
      currentTaskId: "task-1",
      novelsCache: [
        {
          novel_id: "novel-1",
          title: "示例小说",
          filename: "demo.txt",
          file_size: 128,
          upload_time: "2026-04-22T00:00:00Z",
        },
      ],
    });
  });

  it("进入首页布局时应清空当前小说与任务选择，但保留小说缓存", async () => {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    });

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/"]}>
          <Routes>
            <Route element={<AppLayout mode="with-hero-panel" />}>
              <Route index element={<div>home</div>} />
            </Route>
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await waitFor(() => {
      expect(useNovelStore.getState().currentNovelId).toBeNull();
      expect(useNovelStore.getState().currentTaskId).toBeNull();
    });

    expect(useNovelStore.getState().novelsCache).toEqual([
      {
        novel_id: "novel-1",
        title: "示例小说",
        filename: "demo.txt",
        file_size: 128,
        upload_time: "2026-04-22T00:00:00Z",
      },
    ]);
  });
});
