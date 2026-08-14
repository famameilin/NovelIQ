import { createElement } from "react";
import type { ReactNode } from "react";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { StreamEventData } from "@/api/streamTypes";
import { StreamOutput } from "@/components/analysis/StreamOutput";
import { useStreamStore } from "@/store/streamStore";

function motionElement(tagName: string) {
  const Component = (props: {
    children?: ReactNode;
    whileHover?: unknown;
    whileTap?: unknown;
    transition?: unknown;
    variants?: unknown;
    initial?: unknown;
    animate?: unknown;
    exit?: unknown;
    [key: string]: unknown;
  }) => {
    const sanitizedProps = { ...props };
    delete sanitizedProps.whileHover;
    delete sanitizedProps.whileTap;
    delete sanitizedProps.transition;
    delete sanitizedProps.variants;
    delete sanitizedProps.initial;
    delete sanitizedProps.animate;
    delete sanitizedProps.exit;
    return createElement(tagName, sanitizedProps, props.children);
  };
  Component.displayName = `motion-${tagName}`;
  return Component;
}

vi.mock("framer-motion", () => ({
  motion: new Proxy(
    {},
    {
      get: (_target, key: string) => motionElement(key),
    },
  ),
  AnimatePresence: ({ children }: { children?: ReactNode }) => <>{children}</>,
}));

/**
 * StreamOutput 需要真实消费 Zustand 多流状态，因此测试直接用 store seed 当前 task/progress 与并行流事件
 */
function createLLMEvent(overrides: Partial<StreamEventData>): StreamEventData {
  return {
    action: "output",
    stage: "annotate",
    sub_stage: "phase3",
    chunk_id: 3,
    stream_id: null,
    current: 3,
    total: 10,
    percent: 35,
    sub_percent: 60,
    content: "",
    message: "phase3 进行中",
    status: null,
    ...overrides,
  };
}

/**
 * 输出面板依赖当前 task 和 progress 才会渲染，需要统一初始化上下文避免每个测试重复手写 store 搭建
 */
function seedTaskContext(taskId: string) {
  act(() => {
    useStreamStore.getState().setTaskId(taskId);
    useStreamStore.getState().updateProgress(
      createLLMEvent({
        action: "progress",
        content: "",
      }),
    );
  });
}

describe("StreamOutput 区块流展示", () => {
  beforeEach(() => {
    act(() => {
      useStreamStore.getState().reset();
    });
  });

  afterEach(() => {
    act(() => {
      useStreamStore.getState().reset();
    });
  });

  /**
   * chapter_agent 是标注阶段唯一的子阶段边界（后端不再下发 phase1-4）；
   * 即便当前 chapter_agent 还没收到任何事件，主面板也必须先立住 pending 骨架，避免阶段切换闪断
   */
  it("chapter_agent 尚未收到流事件时也应保持 pending 骨架", () => {
    act(() => {
      useStreamStore.getState().setTaskId("task-pending-chapter-agent");
      useStreamStore.getState().updateProgress(
        createLLMEvent({
          action: "start",
          sub_stage: "chapter_agent",
          chunk_id: 1,
          current: 1,
          total: 10,
          percent: 17,
          sub_percent: 0,
          content: "",
          message: "开始 chapter_agent",
        }),
      );
    });

    render(<StreamOutput taskId="task-pending-chapter-agent" />);

    expect(screen.getByText("开始 chapter_agent")).toBeInTheDocument();
    expect(screen.getByText(/模型输出尚未到达/)).toBeInTheDocument();
    expect(screen.queryByText("LLM 输出将在模型推理阶段显示...")).not.toBeInTheDocument();
    expect(screen.queryByText("模型思考中")).not.toBeInTheDocument();
    expect(screen.queryByText("模型输出")).not.toBeInTheDocument();
  });

  it("单流输出时展示模型输出区块且不显示多流入口", () => {
    seedTaskContext("task-1");
    act(() => {
      useStreamStore.getState().appendLLMOutput(
        createLLMEvent({
          action: "output",
          content: "单流输出内容",
        }),
      );
    });

    render(<StreamOutput taskId="task-1" />);

    expect(screen.getByText("模型输出")).toBeInTheDocument();
    expect(screen.getByText("单流输出内容")).toBeInTheDocument();
    expect(screen.queryByText("模型思考中")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "查看全部流" })).not.toBeInTheDocument();
  });

  it("工具调用到达后展示模型思考中区块（工具名+状态），思考完成后自动收起", async () => {
    const user = userEvent.setup();
    seedTaskContext("task-1");
    act(() => {
      useStreamStore.getState().appendLLMOutput(
        createLLMEvent({
          action: "tool_call",
          content: "resolve_case",
          message: "正在调用工具 resolve_case",
          status: "started",
        }),
      );
    });

    render(<StreamOutput taskId="task-1" />);

    // 思考块是最后一块且输出未到 → 默认展开
    expect(screen.getByRole("button", { name: /模型思考中/ })).toBeInTheDocument();
    expect(screen.getByText("resolve_case")).toBeInTheDocument();
    expect(screen.getByText("进行中")).toBeInTheDocument();

    // 工具执行成功后状态更新为成功
    act(() => {
      useStreamStore.getState().appendLLMOutput(
        createLLMEvent({
          action: "tool_call",
          content: "resolve_case",
          message: "工具 resolve_case 执行成功",
          status: "success",
        }),
      );
    });

    expect(screen.getByText("成功")).toBeInTheDocument();
    expect(screen.queryByText("进行中")).not.toBeInTheDocument();

    // 模型输出到达后思考块自动收起（默认收起），工具名不再直接可见
    act(() => {
      useStreamStore.getState().appendLLMOutput(
        createLLMEvent({
          action: "output",
          content: "输出内容",
        }),
      );
    });

    expect(screen.getByText("模型输出")).toBeInTheDocument();
    expect(screen.queryByText("resolve_case")).not.toBeInTheDocument();

    // 点击标题可手动展开查看工具列表
    await user.click(screen.getByRole("button", { name: /模型思考中/ }));
    expect(screen.getByText("resolve_case")).toBeInTheDocument();
    expect(screen.getByText("成功")).toBeInTheDocument();
  });

  it("标注 Agent 进入新 chunk 尚无新流时应回退展示同 chunk 最近输出", () => {
    act(() => {
      useStreamStore.getState().setTaskId("task-phase-fallback");
      useStreamStore.getState().updateProgress(
        createLLMEvent({
          action: "start",
          sub_stage: "chapter_agent",
          chunk_id: 244,
          current: 244,
          total: 255,
          percent: 77,
          sub_percent: 75,
          content: "",
          message: "开始 chapter_agent",
        }),
      );
      // 旧合同（phase2）留下的同 chunk 输出：仅用于在 chapter_agent 契约下验证回退链仍可用
      useStreamStore.getState().appendLLMOutput(
        createLLMEvent({
          action: "output",
          sub_stage: "phase2",
          chunk_id: 244,
          current: 244,
          total: 255,
          percent: 76.98,
          sub_percent: 25,
          content: "智子向人类发送五个字信息，",
        }),
      );
    });

    render(<StreamOutput taskId="task-phase-fallback" />);

    expect(screen.getByText("智子向人类发送五个字信息，")).toBeInTheDocument();
    expect(screen.queryByText(/模型输出尚未到达/)).not.toBeInTheDocument();
  });

  it("同 chunk 的工具调用落在旧合同 sub_stage 时也应在思考区块回退展示", () => {
    act(() => {
      useStreamStore.getState().setTaskId("task-thinking-fallback");
      useStreamStore.getState().updateProgress(
        createLLMEvent({
          action: "start",
          sub_stage: "chapter_agent",
          chunk_id: 244,
          current: 244,
          total: 255,
          percent: 77,
          sub_percent: 75,
          content: "",
          message: "开始 chapter_agent",
        }),
      );
      useStreamStore.getState().appendLLMOutput(
        createLLMEvent({
          action: "output",
          sub_stage: "phase2",
          chunk_id: 244,
          content: "phase2 输出",
        }),
      );
      useStreamStore.getState().appendLLMOutput(
        createLLMEvent({
          action: "tool_call",
          sub_stage: "phase1",
          chunk_id: 244,
          content: "search_pool",
          message: "正在调用工具 search_pool",
          status: "started",
        }),
      );
    });

    render(<StreamOutput taskId="task-thinking-fallback" />);

    expect(screen.getByText("模型思考中")).toBeInTheDocument();
    expect(screen.getByText("search_pool")).toBeInTheDocument();
    expect(screen.getByText("进行中")).toBeInTheDocument();
  });

  it("chapter_agent 首段文本到达后应停止回退旧 sub_stage 事件，避免旧输出和旧思考串进新阶段", async () => {
    const user = userEvent.setup();
    act(() => {
      useStreamStore.getState().setTaskId("task-phase3-phase4-boundary");
      useStreamStore.getState().updateProgress(
        createLLMEvent({
          action: "start",
          sub_stage: "chapter_agent",
          chunk_id: 244,
          current: 244,
          total: 255,
          percent: 77,
          sub_percent: 75,
          content: "",
          message: "开始 chapter_agent",
        }),
      );
      useStreamStore.getState().appendLLMOutput(
        createLLMEvent({
          action: "output",
          sub_stage: "phase3",
          chunk_id: 244,
          content: "phase3 输出",
        }),
      );
      useStreamStore.getState().appendLLMOutput(
        createLLMEvent({
          action: "tool_call",
          sub_stage: "phase3",
          chunk_id: 244,
          content: "search_pool",
          message: "正在调用工具 search_pool",
          status: "started",
        }),
      );
    });

    render(<StreamOutput taskId="task-phase3-phase4-boundary" />);

    expect(screen.getByText("phase3 输出")).toBeInTheDocument();
    expect(screen.getByText("search_pool")).toBeInTheDocument();

    act(() => {
      useStreamStore.getState().appendLLMOutput(
        createLLMEvent({
          action: "output",
          sub_stage: "chapter_agent",
          chunk_id: 244,
          content: "chapter_agent 输出",
        }),
      );
    });

    expect(screen.getByText("chapter_agent 输出")).toBeInTheDocument();
    expect(screen.queryByText("phase3 输出")).not.toBeInTheDocument();
    expect(screen.queryByText("search_pool")).not.toBeInTheDocument();

    act(() => {
      useStreamStore.getState().appendLLMOutput(
        createLLMEvent({
          action: "tool_call",
          sub_stage: "chapter_agent",
          chunk_id: 244,
          content: "resolve_case",
          message: "正在调用工具 resolve_case",
          status: "started",
        }),
      );
    });

    await waitFor(() => {
      expect(screen.getByText("resolve_case")).toBeInTheDocument();
      expect(screen.queryByText("search_pool")).not.toBeInTheDocument();
    });
    await user.click(screen.getByRole("button", { name: /模型思考中/ }));
  });

  it("多流时应默认显示最近更新流，并允许主面板切换", async () => {
    const user = userEvent.setup();
    seedTaskContext("task-2");
    act(() => {
      useStreamStore.getState().appendLLMOutput(
        createLLMEvent({
          action: "output",
          stream_id: "phase3-3-1",
          content: "甲流输出",
        }),
      );
      useStreamStore.getState().appendLLMOutput(
        createLLMEvent({
          action: "output",
          stream_id: "phase3-3-2",
          content: "乙流输出",
        }),
      );
    });

    render(<StreamOutput taskId="task-2" />);

    expect(screen.getByText(/并行 2 条流/)).toBeInTheDocument();
    expect(screen.getByText("乙流输出")).toBeInTheDocument();
    expect(screen.queryByText("甲流输出")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "并行流 1" }));

    expect(screen.getByText("甲流输出")).toBeInTheDocument();
    expect(screen.queryByText("乙流输出")).not.toBeInTheDocument();
  });

  it("查看全部流时应支持列表切换详情，无工具调用的流不显示思考区块", async () => {
    const user = userEvent.setup();
    seedTaskContext("task-3");
    act(() => {
      useStreamStore.getState().appendLLMOutput(
        createLLMEvent({
          action: "output",
          stream_id: "phase3-3-1",
          content: "甲流输出",
        }),
      );
      useStreamStore.getState().appendLLMOutput(
        createLLMEvent({
          action: "output",
          stream_id: "phase3-3-2",
          content: "乙流输出",
        }),
      );
      useStreamStore.getState().appendLLMOutput(
        createLLMEvent({
          action: "tool_call",
          stream_id: "phase3-3-2",
          content: "resolve_case",
          message: "正在调用工具 resolve_case",
          status: "started",
        }),
      );
    });

    render(<StreamOutput taskId="task-3" />);

    await user.click(screen.getByRole("button", { name: "查看全部流" }));

    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText("Phase3 多流输出")).toBeInTheDocument();
    expect(within(dialog).getByText("模型思考中")).toBeInTheDocument();
    expect(within(dialog).getByText("resolve_case")).toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: /并行流 1/ }));
    await waitFor(() => {
      const updatedDialog = screen.getByRole("dialog");
      expect(within(updatedDialog).queryByText("模型思考中")).not.toBeInTheDocument();
      expect(within(updatedDialog).getByText("甲流输出")).toBeInTheDocument();
    });
  });
});
