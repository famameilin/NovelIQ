import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { GraphChange } from "@/api/types";
import { useGraphDeepLinkSelection } from "@/pages/graph/useGraphDeepLinkSelection";

const navigateMock = vi.fn();

/**
 * 2026-08-12 用于锁住图谱页 deep-link 选择逻辑：
 * 首屏默认选中、change_id 命中/miss、chunk 唯一命中、手动选择后清除提示、
 * load-more 合并进新变化后自动补选中、任务切换重置
 */
function createChange(changeId: string, effectiveChunkId: number): GraphChange {
  return {
    change_id: changeId,
    change_kind: "relation",
    graph_version_id: "graph-version-1",
    chapter_id: 1,
    chapter_order: 1,
    fact_id: `fact-${changeId}`,
    fact_revision: 1,
    effective_chunk_id: effectiveChunkId,
    changes: [{ change_kind: "assert" }],
    relation_id: `relation-${changeId}`,
    relation_version_id: 1,
    relation_revision: 1,
    from_entity_id: 1,
    to_entity_id: 2,
    from_name: "甲",
    to_name: "乙",
    relation_type: "盟友",
    relation_change_kind: "assert",
    directionality: "bidirectional",
    relation_semantics: "ordinary",
  };
}

interface DeepLinkHookProps {
  urlChangeId?: string | null;
  urlSelectedChunk?: string | null;
  loadedChanges?: GraphChange[];
  taskScopeId?: string | null;
}

const FIRST_PAGE_CHANGES = [createChange("relation:12:1", 12), createChange("state:13:1", 13)];

function renderDeepLinkHook(initialProps: DeepLinkHookProps = {}) {
  return renderHook(
    ({ urlChangeId, urlSelectedChunk, loadedChanges, taskScopeId }: DeepLinkHookProps) => {
      const effectiveChanges = loadedChanges ?? FIRST_PAGE_CHANGES;
      const sortedChanges = [...effectiveChanges].sort(
        (left, right) => right.effective_chunk_id - left.effective_chunk_id,
      );
      return useGraphDeepLinkSelection({
        novelId: "novel-1",
        taskScopeId: taskScopeId ?? "task-a",
        timelineUrl: "/novels/novel-1/timeline?task_id=task-a",
        urlChangeId: urlChangeId ?? null,
        urlSelectedChunk: urlSelectedChunk ?? null,
        loadedChanges: effectiveChanges,
        sortedChanges,
        navigate: navigateMock,
      });
    },
    { initialProps },
  );
}

describe("useGraphDeepLinkSelection", () => {
  beforeEach(() => {
    navigateMock.mockReset();
  });

  it("无 deep-link 时默认选中排序后的第一条变化", async () => {
    const { result } = renderDeepLinkHook();

    await waitFor(() => {
      expect(result.current.selectedChange?.change_id).toBe("state:13:1");
    });
    expect(result.current.activeSelectedChangeId).toBe("state:13:1");
    expect(result.current.graphSelectionHint).toBeNull();
  });

  it("change_id 命中当前窗口时自动选中且无提示", async () => {
    const { result } = renderDeepLinkHook({ urlChangeId: "relation:12:1" });

    await waitFor(() => {
      expect(result.current.selectedChange?.change_id).toBe("relation:12:1");
    });
    expect(result.current.graphSelectionHint).toBeNull();
  });

  it("change_id miss 时不回退到同 chunk 其他变化，并提示可加载更多", async () => {
    const { result } = renderDeepLinkHook({ urlChangeId: "relation:9999" });

    await waitFor(() => {
      expect(result.current.selectedChange).toBeNull();
    });
    expect(result.current.graphSelectionHint).toBe(
      "未在当前图谱变化窗口定位到指定变化，可能在后页，点击加载更多可继续查找。",
    );
  });

  it("chunk-only deep-link 在当前窗口唯一命中时自动选中", async () => {
    const { result } = renderDeepLinkHook({ urlSelectedChunk: "12" });

    await waitFor(() => {
      expect(result.current.selectedChange?.change_id).toBe("relation:12:1");
    });
  });

  it("用户手动选择后清除 deep-link 提示并同步 URL", async () => {
    const { result } = renderDeepLinkHook({ urlChangeId: "relation:9999" });

    await waitFor(() => {
      expect(result.current.graphSelectionHint).not.toBeNull();
    });

    act(() => {
      result.current.handleSelectChange(createChange("relation:12:1", 12));
    });

    expect(result.current.selectedChange?.change_id).toBe("relation:12:1");
    expect(result.current.graphSelectionHint).toBeNull();
    expect(navigateMock).toHaveBeenCalledWith(
      "/novels/novel-1/graph?task_id=task-a&selected_chunk=12&change_id=relation%3A12%3A1",
      { replace: true },
    );
  });

  it("load-more 合并进新变化后，miss 的 change_id 自动补选中并清除提示", async () => {
    const firstPage = [createChange("relation:12:1", 12)];
    const { result, rerender } = renderDeepLinkHook({
      urlChangeId: "relation:20:1",
      loadedChanges: firstPage,
    });

    await waitFor(() => {
      expect(result.current.selectedChange).toBeNull();
      expect(result.current.graphSelectionHint).not.toBeNull();
    });

    // 模拟 load-more：第二页并入 relation:20:1
    rerender({
      urlChangeId: "relation:20:1",
      loadedChanges: [createChange("relation:20:1", 20), ...firstPage],
    });

    await waitFor(() => {
      expect(result.current.selectedChange?.change_id).toBe("relation:20:1");
    });
    expect(result.current.graphSelectionHint).toBeNull();
  });

  it("任务切换时重置 deep-link 选择状态", async () => {
    const { result, rerender } = renderDeepLinkHook({ urlChangeId: "relation:12:1" });

    await waitFor(() => {
      expect(result.current.selectedChange?.change_id).toBe("relation:12:1");
    });

    // 真实场景：任务切换后分页 hook 会清空 loadedChanges，新任务首屏数据尚未到达
    rerender({ urlChangeId: "relation:12:1", taskScopeId: "task-b", loadedChanges: [] });

    await waitFor(() => {
      expect(result.current.selectedChange).toBeNull();
    });
  });
});
