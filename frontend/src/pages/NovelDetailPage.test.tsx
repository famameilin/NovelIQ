import { createElement } from "react";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";

import { NovelDetailPage } from "@/pages/NovelDetailPage";
import { useNovelStore } from "@/store/novelStore";

const getNovelMock = vi.fn();
const createAnalysisTaskMock = vi.fn();
const resumeAnalysisTaskMock = vi.fn();
const batchDeleteTasksMock = vi.fn();
const cancelAnalysisTaskMock = vi.fn();
const getTaskStatusMock = vi.fn();
const getNarrativeStructureMock = vi.fn();
const getEmotionStatsMock = vi.fn();
const getCharacterStatsMock = vi.fn();
const getStyleStatsMock = vi.fn();
const getTopicsMock = vi.fn();
const getDiagnosisMock = vi.fn();
const getChunkCurvesMock = vi.fn();
const navigateMock = vi.fn();
const confirmSpy = vi.spyOn(window, "confirm");

let currentNovelId = "novel-1";
let currentSearchParams = "";

function passthroughComponent(displayName: string) {
  const Component = ({ children }: { children?: ReactNode }) => <div data-testid={displayName}>{children}</div>;
  Component.displayName = displayName;
  return Component;
}

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

vi.mock("react-router-dom", () => ({
  useNavigate: () => navigateMock,
  useParams: () => ({ novelId: currentNovelId }),
  useSearchParams: () => [new URLSearchParams(currentSearchParams)],
}));

vi.mock("framer-motion", () => ({
  motion: new Proxy(
    {},
    {
      get: (_target, key: string) => motionElement(key),
    },
  ),
}));

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
  },
}));

vi.mock("@/api/results", () => ({
  getNarrativeStructure: (...args: unknown[]) => getNarrativeStructureMock(...args),
  getEmotionStats: (...args: unknown[]) => getEmotionStatsMock(...args),
  getCharacterStats: (...args: unknown[]) => getCharacterStatsMock(...args),
  getStyleStats: (...args: unknown[]) => getStyleStatsMock(...args),
  getTopics: (...args: unknown[]) => getTopicsMock(...args),
  getDiagnosis: (...args: unknown[]) => getDiagnosisMock(...args),
  getChunkCurves: (...args: unknown[]) => getChunkCurvesMock(...args),
}));

vi.mock("@/api/novels", () => ({
  getNovel: (...args: unknown[]) => getNovelMock(...args),
}));

vi.mock("@/api/analysis", () => ({
  createAnalysisTask: (...args: unknown[]) => createAnalysisTaskMock(...args),
  resumeAnalysisTask: (...args: unknown[]) => resumeAnalysisTaskMock(...args),
  batchDeleteTasks: (...args: unknown[]) => batchDeleteTasksMock(...args),
  cancelAnalysisTask: (...args: unknown[]) => cancelAnalysisTaskMock(...args),
  getTaskStatus: (...args: unknown[]) => getTaskStatusMock(...args),
}));

vi.mock("@/hooks/useAnalysisStatus", () => ({
  useAnalysisStatus: () => ({
    isConnected: false,
  }),
}));

vi.mock("@/components/layout/PageContainer", () => ({
  PageContainer: passthroughComponent("page-container"),
}));

vi.mock("@/components/common/NovelHeader", () => ({
  NovelHeader: (props: {
    title: string;
    onCreateTask?: () => void;
    onResumeTask?: (taskId: string) => void;
    onDeleteCurrentTask?: () => void;
  }) => (
    <div>
      <div>{props.title}</div>
      <button type="button" onClick={props.onCreateTask}>mock-create-task</button>
      <button type="button" onClick={() => props.onResumeTask?.("task-failed")}>mock-resume-task</button>
      {props.onDeleteCurrentTask && (
        <button type="button" onClick={props.onDeleteCurrentTask}>mock-delete-task</button>
      )}
    </div>
  ),
}));

vi.mock("@/components/common/DiagnosisSummaryCard", () => ({
  DiagnosisSummaryCard: passthroughComponent("diagnosis-summary-card"),
}));

vi.mock("@/components/common/ScoreOverviewCard", () => ({
  ScoreOverviewCard: passthroughComponent("score-overview-card"),
}));

vi.mock("@/components/common/DimensionMiniCard", () => ({
  DimensionMiniCard: passthroughComponent("dimension-mini-card"),
}));

vi.mock("@/components/common/NarrativeStructureBar", () => ({
  NarrativeStructureBar: (props: {
    eventDensity?: Record<string, number> | null;
  }) => (
    <div data-testid="narrative-structure-bar">
      {props.eventDensity ? JSON.stringify(props.eventDensity) : "no-event-density"}
    </div>
  ),
}));

vi.mock("@/components/charts/MiniCurvePreview", () => ({
  MiniCurvePreview: passthroughComponent("mini-curve-preview"),
}));

vi.mock("@/components/analysis/AnalysisProgressPanel", () => ({
  AnalysisProgressPanel: passthroughComponent("analysis-progress-panel"),
}));

function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });
}

function renderNovelDetailPage() {
  const queryClient = createQueryClient();
  return {
    queryClient,
    ...render(
      <QueryClientProvider client={queryClient}>
        <NovelDetailPage />
      </QueryClientProvider>,
    ),
  };
}

describe("NovelDetailPage", () => {
  beforeEach(() => {
    currentNovelId = "novel-1";
    currentSearchParams = "";
    navigateMock.mockReset();
    getNovelMock.mockReset();
    createAnalysisTaskMock.mockReset();
    resumeAnalysisTaskMock.mockReset();
    batchDeleteTasksMock.mockReset();
    cancelAnalysisTaskMock.mockReset();
    getTaskStatusMock.mockReset();
    getNarrativeStructureMock.mockReset();
    getEmotionStatsMock.mockReset();
    getCharacterStatsMock.mockReset();
    getStyleStatsMock.mockReset();
    getTopicsMock.mockReset();
    getDiagnosisMock.mockReset();
    getChunkCurvesMock.mockReset();
    getNovelMock.mockResolvedValue({
      novel_id: "novel-1",
      title: "测试小说",
      filename: "novel.txt",
      upload_time: "2026-04-19T00:00:00Z",
      file_size: 1,
    });
    createAnalysisTaskMock.mockResolvedValue({
      novel_id: "novel-1",
      task_id: "task-new",
      message: "分析任务已启动",
    });
    resumeAnalysisTaskMock.mockResolvedValue({
      novel_id: "novel-1",
      task_id: "task-failed",
      message: "分析任务已继续执行",
    });
    batchDeleteTasksMock.mockResolvedValue({
      success: true,
      message: "成功删除 1 个任务",
      deleted_count: 1,
      failed_count: 0,
      deleted_ids: ["task-old"],
      failed_ids: [],
    });
    getTaskStatusMock.mockResolvedValue({
      novel_id: "novel-1",
      task_id: "task-ready",
      status: "completed",
      progress: 100,
      current_step: "done",
    });
    getNarrativeStructureMock.mockResolvedValue({});
    getEmotionStatsMock.mockResolvedValue({});
    getCharacterStatsMock.mockResolvedValue({});
    getStyleStatsMock.mockResolvedValue({});
    getTopicsMock.mockResolvedValue([]);
    getDiagnosisMock.mockResolvedValue({
      arc_scores: { 沈砚: 8.2 },
      focus_structure: "single",
      focus_characters: ["沈砚"],
      topic_labels: ["成长"],
      main_characters: ["沈砚"],
      core_cast: ["沈砚"],
    });
    getChunkCurvesMock.mockResolvedValue([]);
    confirmSpy.mockReset();
    confirmSpy.mockReturnValue(true);
    useNovelStore.setState({ currentNovelId: null, currentTaskId: null, novelsCache: [] });
  });

  it("跨小说切换后旧任务不得用于新小说查询或固化成 URL（P1-2 修复）", async () => {
    currentNovelId = "novel-2";
    currentSearchParams = "";
    // store 仍停留在小说 1 的旧任务，页面已切到小说 2
    useNovelStore.setState({ currentNovelId: "novel-1", currentTaskId: "task-old", novelsCache: [] });

    renderNovelDetailPage();

    // 旧任务的 taskStatus 轮询不应发出（否则 404）
    expect(getTaskStatusMock).not.toHaveBeenCalledWith("novel-2", "task-old");
    expect(getTaskStatusMock).not.toHaveBeenCalled();
    // URL 不应被回写固化为旧任务 task_id
    expect(navigateMock).not.toHaveBeenCalledWith("/novels/novel-2?task_id=task-old", { replace: true });
    // 页面应进入未选择任务态，而不是用旧任务渲染
    expect(await screen.findByRole("button", { name: "开始分析" })).toBeInTheDocument();
  });

  it("URL deep-link 任务优先于旧 store 状态，不被旧任务回写覆盖（P1-2 修复）", async () => {
    currentNovelId = "novel-2";
    currentSearchParams = "task_id=task-new";
    useNovelStore.setState({ currentNovelId: "novel-1", currentTaskId: "task-old", novelsCache: [] });
    getTaskStatusMock.mockResolvedValue({
      novel_id: "novel-2",
      task_id: "task-new",
      status: "completed",
      progress: 100,
      current_step: "done",
    });

    renderNovelDetailPage();

    // deep-link 的 task-new 同步进 store 后成为唯一查询目标
    await waitFor(() => {
      expect(getTaskStatusMock).toHaveBeenCalledWith("novel-2", "task-new");
    });
    expect(getTaskStatusMock).not.toHaveBeenCalledWith("novel-2", "task-old");
    // 旧 store 状态不得抢先把 URL replace 成旧任务
    expect(navigateMock).not.toHaveBeenCalledWith("/novels/novel-2?task_id=task-old", { replace: true });
  });

  it("空状态点击开始分析时应走创建任务接口", async () => {
    const user = userEvent.setup();
    createAnalysisTaskMock.mockResolvedValue({
      novel_id: "novel-1",
      task_id: "task-new",
      message: "分析任务已创建并启动",
    });
    const { queryClient } = renderNovelDetailPage();
    const invalidateQueriesSpy = vi.spyOn(queryClient, "invalidateQueries");

    await user.click(await screen.findByRole("button", { name: "开始分析" }));

    await waitFor(() => {
      expect(createAnalysisTaskMock).toHaveBeenCalledWith("novel-1");
      expect(invalidateQueriesSpy).toHaveBeenCalledWith({ queryKey: ["tasks", "novel-1"] });
    });
    expect(createAnalysisTaskMock).toHaveBeenCalledTimes(1);
  });

  it("失败任务重试应走继续任务接口", async () => {
    const user = userEvent.setup();
    resumeAnalysisTaskMock.mockResolvedValue({
      novel_id: "novel-1",
      task_id: "task-failed",
      message: "分析任务已继续执行",
    });
    const { queryClient } = renderNovelDetailPage();
    const invalidateQueriesSpy = vi.spyOn(queryClient, "invalidateQueries");

    await user.click(await screen.findByRole("button", { name: "mock-resume-task" }));

    await waitFor(() => {
      expect(resumeAnalysisTaskMock).toHaveBeenCalledWith("novel-1", "task-failed");
      expect(invalidateQueriesSpy).toHaveBeenCalledWith({ queryKey: ["tasks", "novel-1"] });
    });
    expect(resumeAnalysisTaskMock).toHaveBeenCalledTimes(1);
  });

  it("删除当前任务后应清理 URL 中的 task_id", async () => {
    const user = userEvent.setup();
    currentSearchParams = "task_id=task-old";
    useNovelStore.setState({ currentNovelId: "novel-1", currentTaskId: "task-old", novelsCache: [] });
    batchDeleteTasksMock.mockResolvedValue({
      success: true,
      message: "成功删除 1 个任务",
      deleted_count: 1,
      failed_count: 0,
      deleted_ids: ["task-old"],
      failed_ids: [],
    });

    renderNovelDetailPage();

    await user.click(await screen.findByRole("button", { name: "mock-delete-task" }));

    await waitFor(() => {
      expect(batchDeleteTasksMock).toHaveBeenCalledWith("novel-1", ["task-old"]);
    });
    expect(navigateMock).toHaveBeenCalledWith("/novels/novel-1", { replace: true });
  });

  it("删除失败响应不应清理当前任务或误报成功", async () => {
    const user = userEvent.setup();
    const toastErrorSpy = vi.mocked(toast.error);
    currentSearchParams = "task_id=task-old";
    useNovelStore.setState({ currentNovelId: "novel-1", currentTaskId: "task-old", novelsCache: [] });
    batchDeleteTasksMock.mockResolvedValue({
      success: false,
      message: "删除失败: 1 个任务无法删除",
      deleted_count: 0,
      failed_count: 1,
      deleted_ids: [],
      failed_ids: [{ task_id: "task-old", reason: "任务正在running中，请先取消任务后再删除" }],
    });

    renderNovelDetailPage();

    await user.click(await screen.findByRole("button", { name: "mock-delete-task" }));

    await waitFor(() => {
      expect(batchDeleteTasksMock).toHaveBeenCalledWith("novel-1", ["task-old"]);
      expect(toastErrorSpy).toHaveBeenCalledWith(
        "删除任务失败: 任务正在running中，请先取消任务后再删除",
      );
    });
    expect(useNovelStore.getState().currentTaskId).toBe("task-old");
    expect(navigateMock).not.toHaveBeenCalledWith("/novels/novel-1", { replace: true });
  });

  it("详情页应将事件密度传给叙事结构卡片", async () => {
    currentSearchParams = "task_id=task-ready";
    useNovelStore.setState({ currentNovelId: "novel-1", currentTaskId: null, novelsCache: [] });
    getTaskStatusMock.mockResolvedValue({
      novel_id: "novel-1",
      task_id: "task-ready",
      status: "completed",
      progress: 100,
      current_step: "done",
    });
    getNarrativeStructureMock.mockResolvedValue({
      act1_ratio: 0.1,
      act2_ratio: 0.6,
      act3_ratio: 0.3,
      event_density: {
        冲突: 0.5,
        铺垫: 0.3,
        转折: 0.2,
      },
    });

    renderNovelDetailPage();

    await waitFor(() => {
      expect(screen.getByTestId("narrative-structure-bar")).toHaveTextContent(
        JSON.stringify({
          冲突: 0.5,
          铺垫: 0.3,
          转折: 0.2,
        }),
      );
    });
  });

  it("diagnosis 合法为 null 时仍应渲染主内容而不是空白主体区", async () => {
    currentSearchParams = "task_id=task-ready";
    useNovelStore.setState({ currentNovelId: "novel-1", currentTaskId: null, novelsCache: [] });
    getTaskStatusMock.mockResolvedValue({
      novel_id: "novel-1",
      task_id: "task-ready",
      status: "completed",
      progress: 100,
      current_step: "done",
    });
    getDiagnosisMock.mockResolvedValue(null);
    getNarrativeStructureMock.mockResolvedValue({});
    getEmotionStatsMock.mockResolvedValue({});
    getCharacterStatsMock.mockResolvedValue({});
    getStyleStatsMock.mockResolvedValue({});
    getTopicsMock.mockResolvedValue([]);
    getChunkCurvesMock.mockResolvedValue([]);

    renderNovelDetailPage();

    await waitFor(() => {
      expect(screen.getByText("暂无诊断数据")).toBeInTheDocument();
      expect(screen.getByTestId("score-overview-card")).toBeInTheDocument();
    });
  });

  it("旧 diagnosis 合同被判重跑时应显示统一重跑态", async () => {
    currentSearchParams = "task_id=task-ready";
    useNovelStore.setState({ currentNovelId: "novel-1", currentTaskId: null, novelsCache: [] });
    getTaskStatusMock.mockResolvedValue({
      novel_id: "novel-1",
      task_id: "task-ready",
      status: "completed",
      progress: 100,
      current_step: "done",
    });
    getDiagnosisMock.mockResolvedValue({
      rerun_required: true,
      rerun_reason: "focus_contract_incomplete",
    });
    getNarrativeStructureMock.mockResolvedValue({});
    getEmotionStatsMock.mockResolvedValue({});
    getCharacterStatsMock.mockResolvedValue({});
    getStyleStatsMock.mockResolvedValue({});
    getTopicsMock.mockRejectedValue({
      isAxiosError: true,
      response: {
        status: 409,
        data: {
          detail: {
            code: "diagnosis_rerun_required",
            reason: "focus_contract_incomplete",
          },
        },
      },
    });
    getChunkCurvesMock.mockResolvedValue([]);

    renderNovelDetailPage();

    await waitFor(() => {
      expect(screen.getByText("当前结果需要重新分析")).toBeInTheDocument();
      expect(screen.queryByTestId("diagnosis-summary-card")).not.toBeInTheDocument();
      expect(screen.queryByText("数据加载失败")).not.toBeInTheDocument();
    });
  });

  it("运行中任务应先显示进度态且不提前请求结果接口", async () => {
    currentSearchParams = "task_id=task-running";
    useNovelStore.setState({ currentNovelId: "novel-1", currentTaskId: null, novelsCache: [] });
    getTaskStatusMock.mockResolvedValue({
      novel_id: "novel-1",
      task_id: "task-running",
      status: "running",
      progress: 12,
      current_step: "preprocess",
      stage: "preprocess",
      message: "任务执行中",
    });

    renderNovelDetailPage();

    expect(await screen.findByTestId("analysis-progress-panel")).toBeInTheDocument();
    expect(getNarrativeStructureMock).not.toHaveBeenCalled();
    expect(getEmotionStatsMock).not.toHaveBeenCalled();
    expect(getCharacterStatsMock).not.toHaveBeenCalled();
    expect(getStyleStatsMock).not.toHaveBeenCalled();
    expect(getTopicsMock).not.toHaveBeenCalled();
    expect(getDiagnosisMock).not.toHaveBeenCalled();
    expect(getChunkCurvesMock).not.toHaveBeenCalled();
  });

  it("已失败任务应显示友好失败提示而非数据加载失败", async () => {
    currentSearchParams = "task_id=task-failed";
    useNovelStore.setState({ currentNovelId: "novel-1", currentTaskId: null, novelsCache: [] });
    getTaskStatusMock.mockResolvedValue({
      novel_id: "novel-1",
      task_id: "task-failed",
      status: "failed",
      progress: 0,
      current_step: "done",
    });
    const notCompleteError = {
      isAxiosError: true,
      response: {
        status: 400,
        data: {
          detail: "分析未完成，当前状态: failed",
          error_type: "AnalysisNotCompleteError",
          status_code: 400,
          run_status: "failed",
        },
      },
    };
    getNarrativeStructureMock.mockRejectedValue(notCompleteError);
    getEmotionStatsMock.mockRejectedValue(notCompleteError);
    getCharacterStatsMock.mockRejectedValue(notCompleteError);
    getStyleStatsMock.mockRejectedValue(notCompleteError);
    getTopicsMock.mockRejectedValue(notCompleteError);
    getDiagnosisMock.mockRejectedValue(notCompleteError);
    getChunkCurvesMock.mockRejectedValue(notCompleteError);

    renderNovelDetailPage();

    await waitFor(() => {
      expect(screen.getByText("分析任务已失败")).toBeInTheDocument();
      expect(screen.getByText(/请重新发起分析/)).toBeInTheDocument();
      expect(screen.queryByText("数据加载失败")).not.toBeInTheDocument();
    });
  });
});
