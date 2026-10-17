import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { vi } from "vitest";
import type { AxiosResponse } from "axios";
import { apiClient } from "@/api/client";
import { narrativeResponse } from "@/mocks/narrativeData";
import { EventTreesPage } from "@/pages/EventTreesPage";
import { TimelinePage } from "@/pages/TimelinePage";
import { useNovelStore } from "@/store/novelStore";

export { chapters, changes, arc, eventA, eventB, childEvent, grandchildEvent, tree, timeline, treeDetail } from "@/mocks/narrativeData";

/** 使用正式 API 适配器，测试返回值与新契约保持一致 */
export function installNarrativeApi() {
  localStorage.clear();
  useNovelStore.setState({ currentNovelId: "novel-1", currentTaskId: "task-a", novelsCache: [] });
  return vi.spyOn(apiClient, "get").mockImplementation(async (url, config) => {
    const path = String(url);
    const params = config?.params ?? {};
    const result = narrativeResponse(path, new URLSearchParams(Object.entries(params).map(([key, value]) => [key, String(value)])));
    const data = result.data;
    return { data, status: 200 } as AxiosResponse;
  });
}

export function renderNarrative(url = "/novels/novel-1/timeline?task_id=task-a") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const router = createMemoryRouter([
    { path: "/novels/:novelId/timeline", element: <TimelinePage /> },
    { path: "/novels/:novelId/event-trees", element: <EventTreesPage /> },
  ], { initialEntries: [url] });
  return { ...render(<QueryClientProvider client={client}><RouterProvider router={router} /></QueryClientProvider>), router };
}
