import { act, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useAnalysisStatus } from "@/hooks/useAnalysisStatus";
import type { SSEEventType } from "@/api/streamTypes";

const getTaskStatusMock = vi.fn();
const disconnectMock = vi.fn();
let mockedIsConnected = false;
let latestSSEUrl: string | null | undefined;
let latestSSEHandlers:
  | {
      onEvent?: (eventType: SSEEventType | "message", data: unknown) => void;
      onError?: () => void;
    }
  | null = null;

const streamStoreState = {
  setConnected: vi.fn(),
  setTaskId: vi.fn(),
  updateProgress: vi.fn(),
  appendLLMOutput: vi.fn(),
  setError: vi.fn(),
  setStageDuration: vi.fn(),
  reset: vi.fn(),
};

vi.mock("@/api/analysis", () => ({
  getTaskStatus: (...args: unknown[]) => getTaskStatusMock(...args),
}));

vi.mock("@/hooks/useEventSource", () => ({
  useSSEListener: (url: string | null, options?: typeof latestSSEHandlers) => {
    latestSSEUrl = url;
    latestSSEHandlers = options ?? null;
    return {
      isConnected: mockedIsConnected,
      disconnect: disconnectMock,
    };
  },
}));

vi.mock("@/store/streamStore", () => ({
  useStreamStore: () => streamStoreState,
}));

function HookHarness(props: {
  novelId: string | null;
  taskId: string | null;
  onRunning?: () => void;
  onCompleted?: () => void;
  onCancelled?: () => void;
  onFailed?: (error: string) => void;
}) {
  const status = useAnalysisStatus(props.novelId, props.taskId, {
    onRunning: props.onRunning,
    onCompleted: props.onCompleted,
    onCancelled: props.onCancelled,
    onFailed: props.onFailed,
  });
  return (
    <div
      data-testid="analysis-status"
      data-connected={String(status.isConnected)}
    />
  );
}

function createRunningStatus(taskId: string) {
  return {
    novel_id: "novel-1",
    task_id: taskId,
    status: "running" as const,
    progress: 12,
    current_step: "annotate",
    stage: "annotate",
    sub_stage: "phase1",
    current: 1,
    total: 10,
    message: "任务执行中",
  };
}

function emitSSEEvent(eventType: SSEEventType | "message", data: unknown): void {
  if (!latestSSEHandlers?.onEvent) {
    throw new Error("SSE handler not registered");
  }
  act(() => {
    latestSSEHandlers?.onEvent?.(eventType, data);
  });
}

function emitSSEError(): void {
  if (!latestSSEHandlers?.onError) {
    throw new Error("SSE error handler not registered");
  }
  act(() => {
    latestSSEHandlers?.onError?.();
  });
}

describe("useAnalysisStatus", () => {
  beforeEach(() => {
    mockedIsConnected = false;
    latestSSEUrl = undefined;
    latestSSEHandlers = null;
    getTaskStatusMock.mockReset();
    disconnectMock.mockReset();
    streamStoreState.setConnected.mockReset();
    streamStoreState.setTaskId.mockReset();
    streamStoreState.updateProgress.mockReset();
    streamStoreState.appendLLMOutput.mockReset();
    streamStoreState.setError.mockReset();
    streamStoreState.setStageDuration.mockReset();
    streamStoreState.reset.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("检测到已激活的 mock service worker 时跳过 SSE 连接", async () => {
    getTaskStatusMock.mockResolvedValue(createRunningStatus("task-mock"));

    const originalServiceWorker = navigator.serviceWorker;
    Object.defineProperty(navigator, "serviceWorker", {
      configurable: true,
      value: { controller: {} },
    });

    render(<HookHarness novelId="novel-1" taskId="task-mock" />);

    await waitFor(() => {
      expect(getTaskStatusMock).toHaveBeenCalledWith("novel-1", "task-mock");
    });
    // mock 运行态下 SSE URL 应为 null（避免与 mock 事件流双写）
    expect(latestSSEUrl).toBeNull();

    Object.defineProperty(navigator, "serviceWorker", {
      configurable: true,
      value: originalServiceWorker,
    });
  });

  it("未启用 mock 时保持 SSE 连接", async () => {
    getTaskStatusMock.mockResolvedValue(createRunningStatus("task-live"));

    render(<HookHarness novelId="novel-1" taskId="task-live" />);

    await waitFor(() => {
      expect(getTaskStatusMock).toHaveBeenCalledWith("novel-1", "task-live");
    });
    expect(latestSSEUrl).toContain("/api/events/tasks/task-live");
  });

  it("会把 pending 任务回填成活跃态并触发 onRunning", async () => {
    const onRunning = vi.fn();
    const onCompleted = vi.fn();
    const onCancelled = vi.fn();
    const onFailed = vi.fn();

    getTaskStatusMock.mockResolvedValue({
      novel_id: "novel-1",
      task_id: "task-pending",
      status: "pending",
      progress: 0,
      message: null,
    });

    render(
      <HookHarness
        novelId="novel-1"
        taskId="task-pending"
        onRunning={onRunning}
        onCompleted={onCompleted}
        onCancelled={onCancelled}
        onFailed={onFailed}
      />,
    );

    await waitFor(() => {
      expect(streamStoreState.setTaskId).toHaveBeenCalledWith("task-pending");
      expect(streamStoreState.updateProgress).toHaveBeenCalledWith(
        expect.objectContaining({
          action: "start",
          stage: "preprocess",
          percent: 0,
          message: "任务待执行",
        }),
      );
      expect(onRunning).toHaveBeenCalledTimes(1);
    });

    expect(onCompleted).not.toHaveBeenCalled();
    expect(onCancelled).not.toHaveBeenCalled();
    expect(onFailed).not.toHaveBeenCalled();
  });

  it("会把 cancelling 任务回填成活跃态并覆盖旧进度", async () => {
    const onRunning = vi.fn();
    const onCompleted = vi.fn();
    const onCancelled = vi.fn();
    const onFailed = vi.fn();

    getTaskStatusMock.mockResolvedValue({
      novel_id: "novel-1",
      task_id: "task-cancelling",
      status: "cancelling",
      progress: 55.5,
      stage: null,
      sub_stage: null,
      current: null,
      total: null,
      message: null,
    });

    render(
      <HookHarness
        novelId="novel-1"
        taskId="task-cancelling"
        onRunning={onRunning}
        onCompleted={onCompleted}
        onCancelled={onCancelled}
        onFailed={onFailed}
      />,
    );

    await waitFor(() => {
      expect(streamStoreState.updateProgress).toHaveBeenCalledWith(
        expect.objectContaining({
          action: "progress",
          stage: "cancelling",
          percent: 55.5,
          message: "任务取消中",
        }),
      );
      expect(onRunning).toHaveBeenCalledTimes(1);
    });

    expect(onCompleted).not.toHaveBeenCalled();
    expect(onCancelled).not.toHaveBeenCalled();
    expect(onFailed).not.toHaveBeenCalled();
  });

  it("首次回填已完成任务时不会重复触发 onCompleted", async () => {
    const onCompleted = vi.fn();

    getTaskStatusMock.mockResolvedValue({
      novel_id: "novel-1",
      task_id: "task-finished",
      status: "completed",
      progress: 100,
      message: "分析完成",
    });

    render(<HookHarness novelId="novel-1" taskId="task-finished" onCompleted={onCompleted} />);

    await waitFor(() => {
      expect(streamStoreState.updateProgress).toHaveBeenCalledWith(
        expect.objectContaining({
          action: "complete",
          stage: "completed",
          percent: 100,
          message: "分析完成",
        }),
      );
    });

    expect(onCompleted).not.toHaveBeenCalled();
  });

  it("HTTP backfill 失败时会显式记录并暴露同步错误", async () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    getTaskStatusMock.mockRejectedValue(new Error("network down"));

    render(<HookHarness novelId="novel-1" taskId="task-error" />);

    await waitFor(() => {
      expect(warnSpy).toHaveBeenCalledWith(
        "Failed to backfill analysis task status",
        expect.any(Error),
      );
      expect(streamStoreState.setError).toHaveBeenCalledWith("任务状态同步失败，正在等待实时事件恢复");
    });

    warnSpy.mockRestore();
  });

  it("接收 task_complete 事件时会更新完成态并触发 onCompleted", async () => {
    const onCompleted = vi.fn();
    getTaskStatusMock.mockResolvedValue(createRunningStatus("task-complete"));

    render(<HookHarness novelId="novel-1" taskId="task-complete" onCompleted={onCompleted} />);

    await waitFor(() => {
      expect(getTaskStatusMock).toHaveBeenCalledWith("novel-1", "task-complete");
    });

    streamStoreState.updateProgress.mockClear();
    onCompleted.mockClear();

    emitSSEEvent("task_complete", {});

    await waitFor(() => {
      expect(streamStoreState.updateProgress).toHaveBeenCalledWith(
        expect.objectContaining({
          action: "complete",
          stage: "completed",
          percent: 100,
          message: "分析完成",
        }),
      );
      expect(onCompleted).toHaveBeenCalledTimes(1);
    });
  });

  it("接收 task_cancelled 事件时会更新取消态并触发 onCancelled", async () => {
    const onCancelled = vi.fn();
    getTaskStatusMock.mockResolvedValue(createRunningStatus("task-cancelled"));

    render(<HookHarness novelId="novel-1" taskId="task-cancelled" onCancelled={onCancelled} />);

    await waitFor(() => {
      expect(getTaskStatusMock).toHaveBeenCalledWith("novel-1", "task-cancelled");
    });

    streamStoreState.updateProgress.mockClear();
    streamStoreState.setError.mockClear();
    onCancelled.mockClear();

    emitSSEEvent("task_cancelled", {});

    await waitFor(() => {
      expect(streamStoreState.updateProgress).toHaveBeenCalledWith(
        expect.objectContaining({
          action: "complete",
          stage: "cancelled",
          percent: 0,
          message: "任务已取消",
        }),
      );
      expect(streamStoreState.setError).toHaveBeenCalledWith(null);
      expect(onCancelled).toHaveBeenCalledTimes(1);
    });
  });

  it("SSE 断开后会显式标记连接中断", async () => {
    getTaskStatusMock.mockResolvedValue(createRunningStatus("task-disconnect"));

    render(<HookHarness novelId="novel-1" taskId="task-disconnect" />);

    await waitFor(() => {
      expect(getTaskStatusMock).toHaveBeenCalledWith("novel-1", "task-disconnect");
    });

    emitSSEEvent("stage_progress", {
      action: "progress",
      stage: "annotate",
      sub_stage: "phase1",
      chapter_id: 2,
      current: 2,
      total: 10,
      percent: 20,
      sub_percent: 50,
      content: "",
      message: "phase1 进行中",
    });

    emitSSEError();

    await waitFor(() => {
      expect(streamStoreState.setConnected).toHaveBeenCalledWith(false);
    });
  });

  it("接收 LLM 流事件时应按流批量透传给 store", async () => {
    getTaskStatusMock.mockResolvedValue(createRunningStatus("task-stream-id"));

    render(<HookHarness novelId="novel-1" taskId="task-stream-id" />);

    await waitFor(() => {
      expect(getTaskStatusMock).toHaveBeenCalledWith("novel-1", "task-stream-id");
    });

    vi.useFakeTimers();
    streamStoreState.appendLLMOutput.mockClear();

    emitSSEEvent("llm_output", {
      action: "output",
      stage: "annotate",
      sub_stage: "phase3",
      chapter_id: 3,
      stream_id: "phase3-3-2",
      current: 3,
      total: 10,
      percent: 35,
      sub_percent: 60,
      content: "乙流",
      message: "phase3 推理中",
    });
    emitSSEEvent("llm_output", {
      action: "output",
      stage: "annotate",
      sub_stage: "phase3",
      chapter_id: 3,
      stream_id: "phase3-3-2",
      current: 3,
      total: 10,
      percent: 35,
      sub_percent: 60,
      content: "输出",
      message: "phase3 推理中",
    });

    expect(streamStoreState.appendLLMOutput).not.toHaveBeenCalled();

    await act(async () => {
      vi.advanceTimersByTime(120);
    });

    expect(streamStoreState.appendLLMOutput).toHaveBeenCalledWith(
      expect.objectContaining({
        stream_id: "phase3-3-2",
        content: "乙流输出",
      }),
    );
  });
});
