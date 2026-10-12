import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { vi } from "vitest";
import type { AxiosResponse } from "axios";
import { apiClient } from "@/api/client";
import { changes, root, arc, eventA, eventB, tree, timeline, treeDetail } from "@/mocks/narrativeData";
import { EventTreesPage } from "@/pages/EventTreesPage";
import { TimelinePage } from "@/pages/TimelinePage";
import { useNovelStore } from "@/store/novelStore";

export { chapters, changes, root, arc, eventA, eventB, tree, timeline, treeDetail } from "@/mocks/narrativeData";

/** 使用正式 API 适配器，测试返回值与新契约保持一致 */
export function installNarrativeApi() {
  localStorage.clear();
  useNovelStore.setState({ currentNovelId: "novel-1", currentTaskId: "task-a", novelsCache: [] });
  return vi.spyOn(apiClient, "get").mockImplementation(async (url, config) => {
    const path = String(url);
    const params = config?.params ?? {};
    let data: unknown;
    if (path.endsWith("/source")) {
      const chapter = Number(params.chapter_id) || 1;
      data = { chapter_id: chapter, title: `章节 ${chapter}`, paragraphs: [{ paragraph_id: chapter, paragraph_index: 0, text: `原文 ${chapter} ` + "正文".repeat(800) }] };
    } else if (path.includes("/timeline/changes/")) {
      data = changes.find(change => path.endsWith(change.progression_change_id));
    } else if (path.endsWith("/timeline")) {
      const result = timeline(Number(params.through_chapter_id) || 1);
      result.changes = result.changes.filter(change => (!params.source_fact_id || change.source_fact_ids.includes(params.source_fact_id)) && (!params.q || change.title.includes(params.q)) && (!params.dimension || change.dimension === params.dimension));
      result.distribution = result.distribution.filter(point => result.changes.some(change => change.chapter_id === point.chapter_id && change.dimension === point.dimension));
      result.total = result.changes.length;
      data = result;
    } else if (path.includes("/event-trees/nodes/")) {
      const id = decodeURIComponent(path.split("/").at(-1)!);
      data = treeDetail([root, arc, eventA, eventB].find(node => node.node_id === id)!);
    } else if (path.endsWith("/event-trees")) {
      if (params.q || params.chapter_id) data = { ...tree, nodes: [root, arc, eventB], total: 1, matches: [{ node_id: eventB.node_id, title: eventB.title, ancestor_ids: ["root", "arc:a"], chapter_id: 3, chapter_order: 3 }] };
      else if (params.expand_all) data = { ...tree, nodes: [root, arc, eventA, ...(params.cursor ? [eventB] : [])], edges: [...tree.edges, { source_id: arc.node_id, target_id: eventA.node_id, kind: "organization" }, ...(params.cursor ? [{ source_id: arc.node_id, target_id: eventB.node_id, kind: "organization" }] : [])], total: 4, next_cursor: params.cursor ? null : "all-second" };
      else if (params.parent_id) {
        const children = params.parent_id === arc.node_id ? [params.cursor ? eventB : eventA] : [];
        data = { ...tree, nodes: [root, arc, ...children], edges: [...tree.edges, ...children.map(node => ({ source_id: node.parent_id!, target_id: node.node_id, kind: "organization" }))], next_cursor: children.length && !params.cursor ? "second" : null, total: children.length ? 2 : 0 };
      }
      else data = tree;
    } else data = {};
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
