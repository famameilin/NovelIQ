import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useAnalysisStatus } from "@/hooks/useAnalysisStatus";
import type { SSEEventType } from "@/api/streamTypes";

const getTaskStatusMock = vi.fn();
const disconnectMock = vi.fn();
let mockedIsConnected = false;
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
  useSSEListener: (_url: string | null, options?: typeof latestSSEHandlers) => {
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
      data-stable={String(status.wsStable)}
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

  it("SSE 断开后会重置稳定态并显式标记连接中断", async () => {
    getTaskStatusMock.mockResolvedValue(createRunningStatus("task-disconnect"));

    render(<HookHarness novelId="novel-1" taskId="task-disconnect" />);

    await waitFor(() => {
      expect(getTaskStatusMock).toHaveBeenCalledWith("novel-1", "task-disconnect");
    });

    emitSSEEvent("stage_progress", {
      action: "progress",
      stage: "annotate",
      sub_stage: "phase1",
      chunk_id: 2,
      current: 2,
      total: 10,
      percent: 20,
      sub_percent: 50,
      content: "",
      message: "phase1 进行中",
    });

    await waitFor(() => {
      expect(screen.getByTestId("analysis-status")).toHaveAttribute("data-stable", "true");
    });

    emitSSEError();

    await waitFor(() => {
      expect(streamStoreState.setConnected).toHaveBeenCalledWith(false);
      expect(screen.getByTestId("analysis-status")).toHaveAttribute("data-stable", "false");
    });
  });
});
