import type { ReactNode } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { TaskRow } from "@/components/analysis/TaskRow";

vi.mock("@/components/ui/button", () => ({
  Button: ({
    children,
    ...props
  }: {
    children?: ReactNode;
    [key: string]: unknown;
  }) => <button {...props}>{children}</button>,
}));

vi.mock("@/components/ui/badge", () => ({
  Badge: ({
    children,
    ...props
  }: {
    children?: ReactNode;
    [key: string]: unknown;
  }) => <span {...props}>{children}</span>,
}));

describe("TaskRow", () => {
  it("为 pending 任务同时提供继续和取消入口", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    const onCancel = vi.fn();
    const onDelete = vi.fn();
    const onResume = vi.fn();

    render(
      <TaskRow
        task={{
          task_id: "pending01",
          status: "pending",
        }}
        isActive={false}
        onSelect={onSelect}
        onCancel={onCancel}
        onDelete={onDelete}
        onResume={onResume}
      />
    );

    await user.click(screen.getByTitle("继续分析"));
    expect(onResume).toHaveBeenCalledWith("pending01");

    const buttons = screen.getAllByRole("button");
    expect(buttons).toHaveLength(2);

    await user.click(buttons[0]);
    expect(onCancel).toHaveBeenCalledWith("pending01");
    expect(onDelete).not.toHaveBeenCalled();
  });

  it("created_at 缺失时应显示未知时间而不是 epoch 假时间", () => {
    render(
      <TaskRow
        task={{
          task_id: "pending02",
          status: "pending",
        }}
        isActive={false}
        onSelect={vi.fn()}
        onCancel={vi.fn()}
        onDelete={vi.fn()}
        onResume={vi.fn()}
      />
    );

    expect(screen.queryByText("未知时间")).not.toBeInTheDocument();
  });

  it("cancelled 任务应提供继续分析入口", async () => {
    const user = userEvent.setup();
    const onResume = vi.fn();

    render(
      <TaskRow
        task={{
          task_id: "cancelled01",
          status: "cancelled",
        }}
        isActive={false}
        onSelect={vi.fn()}
        onCancel={vi.fn()}
        onDelete={vi.fn()}
        onResume={onResume}
      />
    );

    await user.click(screen.getByTitle("继续分析"));
    expect(onResume).toHaveBeenCalledWith("cancelled01");
  });

  it("运行中的任务显示状态标签", () => {

    render(
      <TaskRow
        task={{
          task_id: "running01",
          status: "running",
        }}
        isActive
        onSelect={vi.fn()}
        onCancel={vi.fn()}
        onDelete={vi.fn()}
        onResume={vi.fn()}
      />
    );

    expect(screen.getByText("运行中")).toBeInTheDocument();
  });
});
