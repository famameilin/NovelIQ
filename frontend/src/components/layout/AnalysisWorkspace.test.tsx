import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AnalysisWorkspace } from "@/components/layout/AnalysisWorkspace";

vi.mock("@/components/common/NovelHeader", () => ({
  NovelHeader: ({ title, className }: { title: string; className?: string }) => (
    <div className={className}>{title}</div>
  ),
}));

describe("AnalysisWorkspace.Tabs", () => {
  it("首次激活时再挂载页签内容，并保留访问过的面板", async () => {
    const user = userEvent.setup();

    render(
      <AnalysisWorkspace.Tabs defaultValue="overview">
        <AnalysisWorkspace.Tab value="overview" label="总览">
          <div>总览内容</div>
        </AnalysisWorkspace.Tab>
        <AnalysisWorkspace.Tab value="emotion" label="情绪">
          <div>情绪内容</div>
        </AnalysisWorkspace.Tab>
      </AnalysisWorkspace.Tabs>,
    );

    const overviewPanel = screen.getByText("总览内容").closest('[role="tabpanel"]');
    expect(overviewPanel).toHaveAttribute("data-state", "active");
    expect(screen.queryByText("情绪内容")).not.toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "情绪" }));

    await waitFor(() => {
      expect(screen.getByText("情绪内容").closest('[role="tabpanel"]')).toHaveAttribute(
        "data-state",
        "active",
      );
    });
    expect(overviewPanel).toHaveAttribute("data-state", "inactive");
  });

  it("默认使用固定视口类名", () => {
    const { container } = render(
      <AnalysisWorkspace title="默认布局">
        <AnalysisWorkspace.Tabs defaultValue="overview">
          <AnalysisWorkspace.Tab value="overview" label="总览">
            <div>总览内容</div>
          </AnalysisWorkspace.Tab>
        </AnalysisWorkspace.Tabs>
      </AnalysisWorkspace>,
    );

    const viewport = container.querySelector("main");
    const content = viewport?.children[1];
    const panel = viewport?.querySelector('[role="tabpanel"][data-state="active"]');

    expect(viewport).toHaveClass("h-full", "overflow-hidden");
    expect(content).toHaveClass("flex-1", "overflow-hidden");
    expect(panel).toHaveClass("h-full", "flex-1", "overflow-hidden");
  });

  it("文档流模式把纵向内容交给外层滚动", () => {
    const { container } = render(
      <AnalysisWorkspace title="文档流布局" documentFlow>
        <AnalysisWorkspace.Tabs defaultValue="overview">
          <AnalysisWorkspace.Tab value="overview" label="总览">
            <div>总览内容</div>
          </AnalysisWorkspace.Tab>
        </AnalysisWorkspace.Tabs>
      </AnalysisWorkspace>,
    );

    const viewport = container.querySelector("main");
    const content = viewport?.children[1];
    const panel = viewport?.querySelector('[role="tabpanel"][data-state="active"]');

    expect(viewport).toHaveClass("h-auto", "min-h-full", "overflow-visible");
    expect(content).toHaveClass("flex", "flex-col", "overflow-visible");
    expect(content).not.toHaveClass("flex-1", "overflow-hidden");
    expect(panel).toHaveClass("flex", "flex-col", "overflow-visible");
    expect(panel).not.toHaveClass("h-full", "flex-1", "overflow-hidden");
  });
});
