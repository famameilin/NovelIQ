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
}));

vi.mock("@/hooks/useAnalysisStatus", () => ({
  useAnalysisStatus: () => ({
    isConnected: false,
    wsStable: false,
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
    getNarrativeStructureMock.mockResolvedValue({});
    getEmotionStatsMock.mockResolvedValue({});
    getCharacterStatsMock.mockResolvedValue({});
    getStyleStatsMock.mockResolvedValue({});
    getTopicsMock.mockResolvedValue([]);
    getDiagnosisMock.mockResolvedValue({});
    getChunkCurvesMock.mockResolvedValue([]);
    confirmSpy.mockReset();
    confirmSpy.mockReturnValue(true);
    useNovelStore.setState({ currentNovelId: null, currentTaskId: null, novelsCache: [] });
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

  it("旧 diagnosis 合同被判重跑时应继续渲染诊断卡而不是回退到暂无数据", async () => {
    currentSearchParams = "task_id=task-ready";
    useNovelStore.setState({ currentNovelId: "novel-1", currentTaskId: null, novelsCache: [] });
    getDiagnosisMock.mockResolvedValue({
      rerun_required: true,
      rerun_reason: "focus_contract_incomplete",
    });
    getNarrativeStructureMock.mockResolvedValue({});
    getEmotionStatsMock.mockResolvedValue({});
    getCharacterStatsMock.mockResolvedValue({});
    getStyleStatsMock.mockResolvedValue({});
    getTopicsMock.mockResolvedValue([]);
    getChunkCurvesMock.mockResolvedValue([]);

    renderNovelDetailPage();

    await waitFor(() => {
      expect(screen.getByTestId("diagnosis-summary-card")).toBeInTheDocument();
      expect(screen.queryByText("暂无诊断数据")).not.toBeInTheDocument();
    });
  });
});
