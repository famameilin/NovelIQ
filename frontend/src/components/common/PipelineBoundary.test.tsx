import { render, screen, within } from "@testing-library/react";
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

  it("展示章节发布结果、未确定案例与双方原文证据", async () => {
    vi.mocked(getPipelineSnapshot).mockResolvedValue({
      cutoff_hash: "0123456789abcdef", round_kind: "formal", round_number: 0,
      released_at: "2026-09-30T00:00:00Z", formal_count: 8,
      case_states: { pending: 1, resolved: 1, deferred: 2, contested: 1 }, formal_policy: "正式值不可变",
      pending_dependency_count: 1, contested_partition_count: 1,
      evidence: [{ evidence_id: "evidence-1", chapter_id: 8, paragraph_id: 9, char_start: 0,
        char_end: 6, text_hash: "text-hash", text: "顾霜承认喊声" },
      { evidence_id: "evidence-2", chapter_id: 3, paragraph_id: 4, char_start: 0,
        char_end: 5, text_hash: "text-hash-2", text: "顾霜否认身份" }],
      cases: [{ case_id: "case-1", state: "contested", description: "两章身份判断互斥", type: "身份未确定",
        target_ref: { entity_id: "entity-1" }, source_evidence: ["evidence-1", "evidence-2"],
        continuity_claims: [] }], domain_values: [{ target: "alias:1", state: "contested", projection_hash: "projection-1",
        formal_values: [{ kind: "entity_mention", payload: { name: "顾霜" }, outcome: "accepted", evidence_ids: [] }],
        continuity_values: [{ kind: "identity_binding", payload: { identity_kind: "same" },
          outcome: "conflict", evidence_ids: ["evidence-1", "evidence-2"] }] }],
    });
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={["/novels/novel-1?task_id=task-1"]}>
          <Routes><Route path="/novels/:novelId" element={<PipelineBoundary />} /></Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(await screen.findByLabelText("分析可见边界")).toHaveTextContent("已发布 8 章");
    expect(getPipelineSnapshot).toHaveBeenCalledWith("novel-1", "task-1");
    await userEvent.click(screen.getByText("查看案例与证据"));
    const evidence = screen.getByLabelText("两章身份判断互斥的原文证据");
    expect(within(evidence).getByText("顾霜承认喊声")).toBeVisible();
    expect(within(evidence).getByText("顾霜否认身份")).toBeVisible();
    await userEvent.click(screen.getByText("查看跨章关联记录"));
    expect(screen.getByText("章节标注")).toBeVisible();
    expect(screen.getByText("顾霜")).toBeVisible();
    expect(screen.getByText(/"identity_kind": "same"/)).toBeVisible();
    await userEvent.click(screen.getByText("查看原文证据区间"));
    expect(screen.getAllByText("顾霜承认喊声")).toHaveLength(2);
    expect(screen.getByLabelText("分析可见边界")).toHaveTextContent("案例池：未确定 3 · 互斥判断 1");
    expect(screen.queryByText(/质量监控|人工复核|抽样审计|语义准确率|连续性|下一轮|投影|租约/))
      .not.toBeInTheDocument();
  });
});
