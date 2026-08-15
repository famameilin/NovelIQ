import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { GraphChange, GraphChangesPageInfo, GraphChangesPageResponse } from "@/api/types";
import { useGraphChangePagination } from "@/pages/graph/useGraphChangePagination";

const getGraphChangesMock = vi.fn();

vi.mock("@/api/results", () => ({
  getGraphChanges: (...args: unknown[]) => getGraphChangesMock(...args),
}));

/**
 * 2026-08-12 用于锁住章节图变化分页 hook 的首屏加载、load-more 合并去重、
 * 任务切换清空与快速双击防抖行为
 */
function createChange(changeId: string, effectiveChapterId: number): GraphChange {
  return {
    change_id: changeId,
    change_kind: "relation",
    graph_version_id: "graph-version-1",
    chapter_id: 1,
    chapter_order: 1,
    fact_id: `fact-${changeId}`,
    fact_revision: 1,
    effective_chapter_id: effectiveChapterId,
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

function createPage(
  changes: GraphChange[],
  pageInfo: Partial<GraphChangesPageInfo> = {},
): GraphChangesPageResponse {
  return {
    changes,
    page_info: {
      limit: 200,
      returned_count: changes.length,
      total: changes.length,
      has_more: false,
      next_cursor: null,
      ...pageInfo,
    },
  };
}

interface HookProps {
  novelId?: string;
  taskScopeId: string | null;
}

function renderPaginationHook(initialProps: HookProps = { novelId: "novel-1", taskScopeId: "task-a" }) {
  return renderHook(({ novelId, taskScopeId }: HookProps) => useGraphChangePagination({ novelId, taskScopeId }), {
    initialProps,
  });
}

describe("useGraphChangePagination", () => {
  beforeEach(() => {
    getGraphChangesMock.mockReset();
  });

  it("首屏加载变化列表并按 effective_chapter_id 倒序展示", async () => {
    getGraphChangesMock.mockResolvedValue(
      createPage([createChange("c1", 12), createChange("c2", 13)], { total: 2 }),
    );

    const { result } = renderPaginationHook();

    await waitFor(() => {
      expect(getGraphChangesMock).toHaveBeenCalledWith("novel-1", "task-a");
      expect(result.current.isChangesLoading).toBe(false);
    });
    expect(result.current.loadedChanges.map((change) => change.change_id)).toEqual(["c1", "c2"]);
    expect(result.current.sortedChanges.map((change) => change.change_id)).toEqual(["c2", "c1"]);
    expect(result.current.totalChangeCount).toBe(2);
    expect(result.current.hasMoreChanges).toBe(false);
    expect(result.current.changesLoadError).toBeNull();
  });

  it("load-more 按 change_id 合并去重，重复项不重复展示", async () => {
    getGraphChangesMock
      .mockResolvedValueOnce(
        createPage([createChange("c1", 12), createChange("c2", 13)], {
          total: 3,
          has_more: true,
          next_cursor: "cursor-1",
        }),
      )
      .mockResolvedValueOnce(
        createPage([createChange("c2", 13), createChange("c3", 14)], { total: 3 }),
      );

    const { result } = renderPaginationHook();

    await waitFor(() => {
      expect(result.current.loadedChanges).toHaveLength(2);
    });

    await act(async () => {
      await result.current.handleLoadMoreChanges();
    });

    expect(getGraphChangesMock).toHaveBeenLastCalledWith("novel-1", "task-a", {
      changesCursor: "cursor-1",
      changesLimit: 200,
    });
    const loaded = result.current.loadedChanges.map((change) => change.change_id);
    expect(loaded).toEqual(["c1", "c2", "c3"]);
    expect(result.current.loadedChangeCount).toBe(3);
    expect(result.current.hasMoreChanges).toBe(false);
  });

  it("任务切换会清空旧变化并重新加载新任务", async () => {
    getGraphChangesMock
      .mockResolvedValueOnce(createPage([createChange("c1", 12)]))
      .mockResolvedValueOnce(createPage([createChange("d1", 20)]));

    const { result, rerender } = renderPaginationHook();

    await waitFor(() => {
      expect(result.current.loadedChanges.map((change) => change.change_id)).toEqual(["c1"]);
    });

    rerender({ novelId: "novel-1", taskScopeId: "task-b" });

    await waitFor(() => {
      expect(getGraphChangesMock).toHaveBeenLastCalledWith("novel-1", "task-b");
      expect(result.current.loadedChanges.map((change) => change.change_id)).toEqual(["d1"]);
    });
    expect(result.current.sortedChanges.map((change) => change.change_id)).toEqual(["d1"]);
  });

  it("快速重复调用 load-more 时只发一次请求（同游标在途去重）", async () => {
    getGraphChangesMock
      .mockResolvedValueOnce(
        createPage([createChange("c1", 12)], {
          total: 2,
          has_more: true,
          next_cursor: "cursor-1",
        }),
      )
      .mockResolvedValueOnce(createPage([createChange("c2", 13)], { total: 2 }));

    const { result } = renderPaginationHook();

    await waitFor(() => {
      expect(result.current.loadedChanges).toHaveLength(1);
    });

    // 第二次调用仍处于同一渲染闭包（isChangesLoading 尚未刷新），
    // 依赖 in-flight 游标引用拦截重复请求
    await act(async () => {
      const first = result.current.handleLoadMoreChanges();
      const second = result.current.handleLoadMoreChanges();
      await Promise.all([first, second]);
    });

    expect(getGraphChangesMock).toHaveBeenCalledTimes(2);
    expect(getGraphChangesMock).toHaveBeenLastCalledWith("novel-1", "task-a", {
      changesCursor: "cursor-1",
      changesLimit: 200,
    });
    expect(result.current.loadedChangeCount).toBe(2);
  });

  it("加载失败时暴露错误信息且不中断后续状态", async () => {
    getGraphChangesMock.mockRejectedValueOnce(new Error("network down"));

    const { result } = renderPaginationHook();

    await waitFor(() => {
      expect(result.current.changesLoadError).toBe("network down");
    });
    expect(result.current.isChangesLoading).toBe(false);
    expect(result.current.loadedChanges).toEqual([]);
  });
});
