import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { getPipelineSnapshot } from "@/api/pipeline";
import { PipelineBoundary } from "@/components/common/PipelineBoundary";
import { useNovelStore } from "@/store/novelStore";

vi.mock("@/api/pipeline", () => ({ getPipelineSnapshot: vi.fn() }));

describe("PipelineBoundary", () => {
  beforeEach(() => {
    useNovelStore.getState().clear();
    vi.mocked(getPipelineSnapshot).mockReset();
  });

  it("展示已保存工作、纯文字案例和明确事件关联", async () => {
    vi.mocked(getPipelineSnapshot).mockResolvedValue({
      completed_chapters: 8, total_chapters: 10, saved_work_count: 12,
      case_states: {pending: 1, resolved: 1, deferred: 2, contested: 1},
      cases: [{case_id: "case-1", state: "contested", description: "两章身份判断互斥"}],
      connections: [{connection_id: "link-1", parent_node_id: "n1", node_id: "n2", type: "main",
        author_work_id: "w1", parent_description: "顾霜求援", description: "同伴赶到", parent_chapter_id: 3, chapter_id: 8}],
      works: [],
    });
    render(<QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={["/novels/novel-1?task_id=task-1"]}>
        <Routes><Route path="/novels/:novelId" element={<PipelineBoundary />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>);
    expect(await screen.findByLabelText("分析可见边界")).toHaveTextContent("已完成 8/10 章 · 已保存 12 项工作");
    expect(getPipelineSnapshot).toHaveBeenCalledWith("novel-1", "task-1");
    await userEvent.click(screen.getByText("查看案例"));
    expect(screen.getByText("两章身份判断互斥")).toBeVisible();
    await userEvent.click(screen.getByText("查看事件关联"));
    expect(screen.getByText("顾霜求援 → 同伴赶到")).toBeVisible();
    expect(screen.getByLabelText("分析可见边界")).toHaveTextContent("未确定 3 · 互斥判断 1");
    expect(screen.queryByText(/投影|租约|发布/)).not.toBeInTheDocument();
  });
});
