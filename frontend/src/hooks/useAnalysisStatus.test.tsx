import { render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useAnalysisStatus } from "@/hooks/useAnalysisStatus";

const getTaskStatusMock = vi.fn();
const disconnectMock = vi.fn();

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
  useSSEListener: () => ({
    isConnected: false,
    disconnect: disconnectMock,
  }),
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
  useAnalysisStatus(props.novelId, props.taskId, {
    onRunning: props.onRunning,
    onCompleted: props.onCompleted,
    onCancelled: props.onCancelled,
    onFailed: props.onFailed,
  });
  return null;
}

describe("useAnalysisStatus", () => {
  beforeEach(() => {
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
});
