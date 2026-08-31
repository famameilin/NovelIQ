import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { AnalysisWorkspace } from "@/components/layout/AnalysisWorkspace";

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
});
