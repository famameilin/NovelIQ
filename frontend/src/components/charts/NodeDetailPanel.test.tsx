/**
 * 2026-08-13 P2-5: 生命周期字段（first_seen_chapter/last_seen_chapter）为 null 时
 * 不得渲染"第 null 章"，且整行出场信息应隐藏
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { NodeDetailPanel } from "@/components/charts/NodeDetailPanel";
import type { GraphNode } from "@/api/types";

function createNode(overrides: Partial<GraphNode>): GraphNode {
  return {
    entity_id: 1,
    name: "顾霜",
    entity_type: "character",
    first_seen_chapter: 1,
    last_seen_chapter: 15,
    state_revision: 3,
    state: { primary_role_function: "主角", status: "active" },
    ...overrides,
  };
}

describe("NodeDetailPanel 出场信息", () => {
  it("first_seen_chapter 为 null 时隐藏出场行，不渲染“第 null 章”", () => {
    render(
      <NodeDetailPanel
        node={createNode({ first_seen_chapter: null, last_seen_chapter: null })}
        relatedNodes={[]}
        isOpen
        onClose={() => undefined}
      />,
    );

    expect(screen.queryByText(/第 null 章/)).not.toBeInTheDocument();
    expect(screen.queryByText(/出场/)).not.toBeInTheDocument();
    expect(screen.getByText("顾霜")).toBeInTheDocument();
  });

  it("first_seen_chapter 有值时正常渲染出场区间", () => {
    render(
      <NodeDetailPanel
        node={createNode({ first_seen_chapter: 3, last_seen_chapter: 12 })}
        relatedNodes={[]}
        isOpen
        onClose={() => undefined}
      />,
    );

    expect(screen.getByText("第 3 章 - 第 12 章")).toBeInTheDocument();
  });
});
