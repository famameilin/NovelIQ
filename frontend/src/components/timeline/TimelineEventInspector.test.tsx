import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { TimelineEventNode } from "@/api/types";
import { TimelineEventInspector } from "@/components/timeline/TimelineEventInspector";

const navigateMock = vi.fn();

vi.mock("react-router-dom", () => ({
  useNavigate: () => navigateMock,
}));

describe("TimelineEventInspector", () => {
  it("使用中文业务文案展示事件指标并隐藏内部标识", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    const onSelectTree = vi.fn();
    const node: TimelineEventNode = {
      tree_id: "tree:internal:1",
      root_event_id: "event:internal:root",
      title: "旧案线索浮现",
      summary: "顾霜在铜铃异响中发现旧案线索",
      anchor_chapter_id: 8,
      anchor_chapter_order: 8,
      start_chapter_id: 7,
      end_chapter_id: 9,
      start_progress: 0.2,
      end_progress: 0.3,
      progress: 0.25,
      chapter_ids: [7, 8, 9],
      char_start: 1200,
      char_end: 1800,
      participants: [
        { name: "顾霜", role: " PROTAGONIST " },
        { name: "顾霜", role: " PROTAGONIST " },
        { name: "假山", role: "", entity_type: "location" },
      ],
      character_names: ["顾霜"],
      importance_score: 8.2,
      level: 1,
      phase_name: "发展期",
      main_chain: ["event:internal:root", "event:internal:next"],
      secondary_groups: [{ target_event_id: "event:internal:side", branch: ["event:internal:branch"] }],
      causal_in: 1,
      causal_out: 1,
      node_type: "event",
    };

    render(
      <TimelineEventInspector
        node={node}
        nodes={[node]}
        novelId="novel-1"
        taskId="task-1"
        onClose={onClose}
        onSelectTree={onSelectTree}
        causalEdges={[
          {
            edge_id: "edge-1",
            edge_type: "causal",
            source_event_id: "event:external",
            target_event_id: node.root_event_id,
            source_chapter_id: 6,
            target_chapter_id: 8,
            is_active: true,
            evidence: [{ excerpt: "铜铃异响" }],
          },
        ]}
        foreshadowingEdges={[
          {
            root_event_id: "root-internal",
            tree_id: "tree-internal",
            payoff_event_id: node.root_event_id,
            first_chapter_id: 3,
            last_chapter_id: 8,
            description: "铜铃异响指向山门旧案",
            status: "open",
            active: true,
          },
        ]}
      />,
    );

    expect(screen.getByText("核心事件")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /参与实体/ }));
    expect(screen.getByText("主要人物")).toBeInTheDocument();
    expect(screen.getAllByText("主要人物")).toHaveLength(1);
    expect(screen.getByText("涉及地点：假山")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /关联伏笔/ }));
    expect(screen.getByText("待回收")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "分析数据" }));
    expect(screen.getByText("字符范围")).toBeInTheDocument();
    expect(document.body.textContent).not.toContain(node.tree_id);
    expect(document.body.textContent).not.toContain(node.root_event_id);
    expect(document.body.textContent?.toLowerCase()).not.toContain("protagonist");

    await user.click(screen.getByRole("button", { name: "第 2 步" }));
    expect(onSelectTree).toHaveBeenCalledWith("event:internal:next");
    await user.click(screen.getByRole("button", { name: "在图谱中定位第 8 章" }));
    expect(navigateMock).toHaveBeenCalledWith("/novels/novel-1/graph?task_id=task-1&selected_chapter=8");
    await user.click(screen.getByRole("button", { name: "查看事件树" }));
    expect(navigateMock).toHaveBeenCalledWith(
      "/novels/novel-1/event-trees?task_id=task-1&event_id=event%3Ainternal%3Aroot",
    );
    await user.click(screen.getByRole("button", { name: "关闭事件详情" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
