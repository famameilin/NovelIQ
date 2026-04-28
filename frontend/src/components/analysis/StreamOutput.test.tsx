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

describe("StreamOutput 多流展示", () => {
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
   * 创建时间: 2026-04-28
   * 任务: phase1234-stream-event-contract-closeout
   * 说明: phase1/2/3/4 都属于标注阶段的稳定子阶段边界；
   * 即便当前 phase 还没收到任何 output/thinking，主面板也必须先把双 tab 骨架立住，
   * 否则并行阶段切换时会在“空面板”和“有 tab 面板”之间闪断。
   */
  it.each(["phase1", "phase2", "phase3", "phase4"])(
    "%s 尚未收到流文本时也应保持输出与思考 tab 骨架",
    (phase) => {
      act(() => {
        useStreamStore.getState().setTaskId(`task-pending-${phase}`);
        useStreamStore.getState().updateProgress(
          createLLMEvent({
            action: "start",
            sub_stage: phase,
            chunk_id: 1,
            current: 1,
            total: 10,
            percent: 17,
            sub_percent: phase === "phase1" ? 0 : phase === "phase2" ? 25 : phase === "phase3" ? 50 : 75,
            content: "",
            message: `开始 ${phase}`,
          }),
        );
      });

      render(<StreamOutput taskId={`task-pending-${phase}`} />);

      expect(screen.getByRole("tab", { name: "输出" })).toBeInTheDocument();
      expect(screen.getByRole("tab", { name: "思考" })).toBeInTheDocument();
      expect(screen.getByText(`开始 ${phase}`)).toBeInTheDocument();
      expect(screen.getByText(/模型输出尚未到达/)).toBeInTheDocument();
      expect(screen.queryByText("LLM 输出将在模型推理阶段显示...")).not.toBeInTheDocument();
    },
  );

  it("单流时应继续展示当前输出且不显示多流入口", () => {
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

    expect(screen.getByText("单流输出内容")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "输出" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "思考" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "查看全部流" })).not.toBeInTheDocument();
  });

  it("当前 phase 尚无新流时应回退展示同 chunk 最近输出", () => {
    act(() => {
      useStreamStore.getState().setTaskId("task-phase-fallback");
      useStreamStore.getState().updateProgress(
        createLLMEvent({
          action: "start",
          sub_stage: "phase4",
          chunk_id: 244,
          current: 244,
          total: 255,
          percent: 77,
          sub_percent: 75,
          content: "",
          message: "开始 phase4",
        }),
      );
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

  it("同 chunk 的 thinking 落在其他 phase 时也应在思考 tab 回退展示", async () => {
    const user = userEvent.setup();
    act(() => {
      useStreamStore.getState().setTaskId("task-thinking-fallback");
      useStreamStore.getState().updateProgress(
        createLLMEvent({
          action: "start",
          sub_stage: "phase4",
          chunk_id: 244,
          current: 244,
          total: 255,
          percent: 77,
          sub_percent: 75,
          content: "",
          message: "开始 phase4",
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
          action: "thinking",
          sub_stage: "phase1",
          chunk_id: 244,
          content: "phase1 思考",
        }),
      );
    });

    render(<StreamOutput taskId="task-thinking-fallback" />);

    await user.click(screen.getByRole("tab", { name: "思考" }));
    expect(screen.getByText("phase1 思考")).toBeInTheDocument();
    expect(screen.queryByText(/模型思考尚未到达/)).not.toBeInTheDocument();
  });

  it("phase4 首段文本到达后应停止回退 phase3 旧事件，避免旧输出和旧思考串进新阶段", async () => {
    const user = userEvent.setup();
    act(() => {
      useStreamStore.getState().setTaskId("task-phase3-phase4-boundary");
      useStreamStore.getState().updateProgress(
        createLLMEvent({
          action: "start",
          sub_stage: "phase4",
          chunk_id: 244,
          current: 244,
          total: 255,
          percent: 77,
          sub_percent: 75,
          content: "",
          message: "开始 phase4",
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
          action: "thinking",
          sub_stage: "phase3",
          chunk_id: 244,
          content: "phase3 思考",
        }),
      );
    });

    render(<StreamOutput taskId="task-phase3-phase4-boundary" />);

    expect(screen.getByText("phase3 输出")).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "思考" }));
    expect(screen.getByText("phase3 思考")).toBeInTheDocument();

    act(() => {
      useStreamStore.getState().appendLLMOutput(
        createLLMEvent({
          action: "output",
          sub_stage: "phase4",
          chunk_id: 244,
          content: "phase4 输出",
        }),
      );
    });

    await user.click(screen.getByRole("tab", { name: "输出" }));
    expect(screen.getByText("phase4 输出")).toBeInTheDocument();
    expect(screen.queryByText("phase3 输出")).not.toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "思考" }));
    expect(screen.getByText(/模型思考尚未到达/)).toBeInTheDocument();
    expect(screen.queryByText("phase3 思考")).not.toBeInTheDocument();

    act(() => {
      useStreamStore.getState().appendLLMOutput(
        createLLMEvent({
          action: "thinking",
          sub_stage: "phase4",
          chunk_id: 244,
          content: "phase4 思考",
        }),
      );
    });

    await user.click(screen.getByRole("tab", { name: "思考" }));
    await waitFor(() => {
      expect(screen.getByText("phase4 思考")).toBeInTheDocument();
      expect(screen.queryByText("phase3 思考")).not.toBeInTheDocument();
    });
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

  it("查看全部流时应支持列表切换详情，并在无思考内容时隐藏思考 tab", async () => {
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
          action: "thinking",
          stream_id: "phase3-3-2",
          content: "乙流思考",
        }),
      );
    });

    render(<StreamOutput taskId="task-3" />);

    await user.click(screen.getByRole("button", { name: "查看全部流" }));

    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText("Phase3 多流输出")).toBeInTheDocument();
    expect(within(dialog).getByRole("tab", { name: "思考" })).toBeInTheDocument();

    await user.click(within(dialog).getByRole("tab", { name: "思考" }));
    expect(within(dialog).getByText("乙流思考")).toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: /并行流 1/ }));
    await waitFor(() => {
      const updatedDialog = screen.getByRole("dialog");
      expect(within(updatedDialog).queryByRole("tab", { name: "思考" })).not.toBeInTheDocument();
      expect(within(updatedDialog).getByText("甲流输出")).toBeInTheDocument();
    });
  });
});
