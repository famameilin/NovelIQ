import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";

import type { EventForestResponse, EventTimelineResponse } from "@/api/types";
import { createEventTimeline } from "@/mocks/data";
import { EventTreesPage } from "@/pages/EventTreesPage";
import { TimelinePage } from "@/pages/TimelinePage";
import { useNovelStore } from "@/store/novelStore";

const getTimelineMock = vi.fn();
const getEventForestMock = vi.fn();

vi.mock("@/api/results", () => ({
  getTimeline: (...args: unknown[]) => getTimelineMock(...args),
  getEventForest: (...args: unknown[]) => getEventForestMock(...args),
}));
vi.mock("@/api/novels", () => ({
  getNovel: () => Promise.resolve({ novel_id: "novel-1", title: "测试小说" }),
}));
vi.mock("@/components/layout/AnalysisWorkspace", () => ({
  AnalysisWorkspace: ({ children }: { children: ReactNode }) => <main>{children}</main>,
}));

beforeEach(() => {
  getTimelineMock.mockReset();
  getEventForestMock.mockReset();
  useNovelStore.setState({ currentNovelId: "novel-1", currentTaskId: "task-a", novelsCache: [] });
  const base = createEventTimeline();
  const node = {
    ...base.nodes[0]!, tree_id: "tree-a", root_event_id: "root-a",
    main_chain: ["root-a"], secondary_groups: [], chapter_ids: [1],
    anchor_chapter_id: 1, anchor_chapter_order: 1, start_chapter_id: 1, end_chapter_id: 1,
  };
  const timeline: EventTimelineResponse = {
    ...base, nodes: [node], derived_event_order: ["root-a"],
    causal_edges: [], foreshadowing_edges: [],
  };
  const forest: EventForestResponse = {
    chapter_id: 1, chapter_order: 1, visible_through_chapter_order: 1,
    derived_event_order: ["root-a"],
    event_nodes: [{
      event_id: "root-a", tree_id: "tree-a", chapter_id: 1, chapter_order: 1,
      description: "事件树的开端", cause_role: "root", parent_event_id: null,
      evidence_scope: "chapter", participants: [], anchor_paragraph_ids: [0],
      char_start: 0, char_end: 10, evidence: [{ paragraph_ids: [0] }], causal_event_refs: [],
    }],
    event_trees: [{
      tree_id: "tree-a", root_event_id: "root-a", main_chain: ["root-a"],
      secondary_groups: [], chapter_ids: [1], char_start: 0, char_end: 10,
    }],
    causal_edges: [], foreshadowing_edges: [],
  };
  getTimelineMock.mockResolvedValue(timeline);
  getEventForestMock.mockResolvedValue(forest);
});

it("时间轴悬浮详情可打开对应事件树，树级深链保持在时间轴", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createMemoryRouter([
    { path: "/novels/:novelId/timeline", element: <TimelinePage /> },
    { path: "/novels/:novelId/event-trees", element: <EventTreesPage /> },
  ], { initialEntries: ["/novels/novel-1/timeline?task_id=task-a&tree_id=tree-a&event_id=root-a"] });
  render(<QueryClientProvider client={client}><RouterProvider router={router} /></QueryClientProvider>);

  expect(await screen.findByRole("dialog", { name: "事件详情悬浮框" })).toBeInTheDocument();
  expect(router.state.location.pathname).toBe("/novels/novel-1/timeline");
  await userEvent.setup().click(screen.getByRole("button", { name: "查看事件树" }));

  expect(router.state.location.pathname).toBe("/novels/novel-1/event-trees");
  expect(router.state.location.search).toBe("?task_id=task-a&tree_id=tree-a&event_id=root-a");
  expect(await screen.findByRole("region", { name: "事件树结构" })).toBeInTheDocument();
});
