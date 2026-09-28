import type { ComponentProps, ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TopicsPage } from "@/pages/TopicsPage";
import { useNovelStore } from "@/store/novelStore";

const getTopicsOverviewTabMock = vi.fn();
const getTopicSeriesMock = vi.fn();
const getTopicShiftsMock = vi.fn();
const getTopicEmotionMock = vi.fn();
const navigateMock = vi.fn();

let currentNovelId = "novel-1";
let currentSearchParams = "task_id=task-1";

function passthroughComponent(displayName: string) {
  const Component = ({ children }: { children?: ReactNode }) => <div data-testid={displayName}>{children}</div>;
  Component.displayName = displayName;
  return Component;
}

vi.mock("react-router-dom", () => ({
  useNavigate: () => navigateMock,
  useParams: () => ({ novelId: currentNovelId }),
  useSearchParams: () => [new URLSearchParams(currentSearchParams)],
}));

vi.mock("@/api/results", () => ({
  getTopicSeries: (...args: unknown[]) => getTopicSeriesMock(...args),
  getTopicShifts: (...args: unknown[]) => getTopicShiftsMock(...args),
  getTopicEmotion: (...args: unknown[]) => getTopicEmotionMock(...args),
}));

vi.mock("@/api/tabs", () => ({
  getTopicsOverviewTab: (...args: unknown[]) => getTopicsOverviewTabMock(...args),
  tabQueryKey: (tab: string, novelId: string | undefined, taskId: string | null, ...rest: unknown[]) =>
    ["tabs", novelId, taskId, tab, ...rest],
}));

vi.mock("@/components/layout/PageContainer", () => ({
  PageContainer: passthroughComponent("page-container"),
}));

vi.mock("@/components/common/NovelHeader", () => ({
  NovelHeader: (props: { title: string }) => <div>{props.title}</div>,
}));

vi.mock("@/components/common/DashboardCardShell", () => ({
  DashboardCardShell: (props: { title: string; children?: ReactNode }) => (
    <section>
      <h2>{props.title}</h2>
      <div>{props.children}</div>
    </section>
  ),
}));

vi.mock("@/components/common/TabUnavailableState", () => ({
  TabUnavailableState: passthroughComponent("tab-unavailable-state"),
}));

vi.mock("@/components/common/AnalysisNotCompleteState", () => ({
  AnalysisNotCompleteState: (props: { title?: string; description?: string }) => (
    <div data-testid="analysis-not-complete-state">
      <p>{props.title}</p>
      <p>{props.description}</p>
    </div>
  ),
}));

vi.mock("@/components/topics", () => ({
  TopicWordCloud: passthroughComponent("topic-word-cloud"),
  TopicBarChart: ({ topics }: { topics: Array<{ topic_id: number }> }) => (
    <div data-testid="topic-bar-chart">{topics.map((topic) => topic.topic_id).join(",")}</div>
  ),
  TopicTable: passthroughComponent("topic-table"),
  TopicDistributionChart: passthroughComponent("topic-distribution-chart"),
  TopicKeywordsCard: passthroughComponent("topic-keywords-card"),
  TopicSeriesChart: passthroughComponent("topic-series-chart"),
  TopicShiftsPanel: passthroughComponent("topic-shifts-panel"),
  TopicEmotionPanel: passthroughComponent("topic-emotion-panel"),
}));

vi.mock("@/components/ui/button", () => ({
  Button: ({ children, ...props }: ComponentProps<"button">) => <button {...props}>{children}</button>,
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

function renderTopicsPage() {
  const queryClient = createQueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <TopicsPage />
    </QueryClientProvider>,
  );
}

describe("TopicsPage", () => {
  beforeEach(() => {
    currentNovelId = "novel-1";
    currentSearchParams = "task_id=task-1";
    navigateMock.mockReset();
    getTopicsOverviewTabMock.mockReset();
    getTopicSeriesMock.mockReset();
    getTopicShiftsMock.mockReset();
    getTopicEmotionMock.mockReset();
    getTopicsOverviewTabMock.mockResolvedValue({
      run_id: "task-1",
      model: null,
      topics: [],
      distribution: null,
      chapters: [],
      keywords: [],
      topic_labels: null,
      unavailable_reason: "topic_inference_unavailable: 无 topic_model_runs 契约行",
      keyword_unavailable_reason: null,
    });
    getTopicSeriesMock.mockResolvedValue({
      run_id: "task-1",
      model: null,
      num_topics: null,
      points: [],
      unavailable_reason: "topic_inference_unavailable: 无 topic_model_runs 契约行",
    });
    getTopicShiftsMock.mockResolvedValue({
      run_id: "task-1",
      candidates: [],
      config: { window_size: 6, min_tokens_per_window: 800, score_threshold: 0.3, max_candidates: 20 },
      unavailable_reason: "topic_inference_unavailable: 无 topic_model_runs 契约行",
    });
    getTopicEmotionMock.mockResolvedValue({
      run_id: "task-1",
      model: null,
      emotion: [],
      unavailable_reason: "topic_inference_unavailable: 无 topic_model_runs 契约行",
    });
    useNovelStore.getState().clear();
  });

  it("删除分析详情并让完整主题分布按视图切换、排行翻到末页", async () => {
    getTopicsOverviewTabMock.mockResolvedValue({
      run_id: "task-1",
      model: null,
      topics: Array.from({ length: 25 }, (_, topic_id) => ({
        topic_id,
        words: [`词${topic_id + 1}`],
        weight: (25 - topic_id) / 325,
      })),
      distribution: Array.from({ length: 25 }, (_, topic_id) => ({ topic_id, weight: (25 - topic_id) / 325 })),
      chapters: [],
      keywords: [{ word: "宗门", score: 0.08 }],
      topic_labels: Object.fromEntries(Array.from({ length: 25 }, (_, index) => [String(index), `主题标签${index + 1}`])),
      unavailable_reason: null,
      keyword_unavailable_reason: null,
    });
    getTopicSeriesMock.mockResolvedValue({
      run_id: "task-1",
      model: null,
      num_topics: null,
      points: [],
      unavailable_reason: "topic_inference_unavailable: 无 topic_model_runs 契约行",
    });
    getTopicShiftsMock.mockResolvedValue({
      run_id: "task-1",
      candidates: [],
      config: { window_size: 6, min_tokens_per_window: 800, score_threshold: 0.3, max_candidates: 20 },
      unavailable_reason: null,
    });
    getTopicEmotionMock.mockResolvedValue({
      run_id: "task-1",
      model: null,
      emotion: [],
      unavailable_reason: null,
    });

    renderTopicsPage();

    const user = userEvent.setup();
    expect(await screen.findByText("主题列表 · 25 个")).toBeInTheDocument();
    expect(screen.queryByText("分析详情")).not.toBeInTheDocument();
    const overviewPagination = screen.getByRole("navigation", { name: "主题列表分页" });
    await user.click(within(overviewPagination).getByRole("button", { name: "下一页" }));
    expect(within(overviewPagination).getByText("主题列表 2 / 4")).toBeInTheDocument();
    await user.click(within(overviewPagination).getByRole("button", { name: "下一页" }));
    await user.click(within(overviewPagination).getByRole("button", { name: "下一页" }));
    expect(within(screen.getByLabelText("主题列表")).getAllByRole("button")).toHaveLength(6);
    expect(within(overviewPagination).getByRole("button", { name: "下一页" })).toBeDisabled();

    await user.click(await screen.findByRole("tab", { name: "完整主题分布" }));
    expect(await screen.findByTestId("topic-bar-chart")).toHaveTextContent("0,1,2,3,4,5,6,7,8,9");
    const rankingPagination = screen.getByRole("navigation", { name: "主题权重分页" });
    await user.click(within(rankingPagination).getByRole("button", { name: "下一页" }));
    await user.click(within(rankingPagination).getByRole("button", { name: "下一页" }));
    expect(screen.getByTestId("topic-bar-chart")).toHaveTextContent("20,21,22,23,24");
    expect(within(rankingPagination).getByRole("button", { name: "下一页" })).toBeDisabled();

    const views = screen.getByRole("group", { name: "主题分布视图" });
    await user.click(within(views).getByRole("button", { name: "全书与章节" }));
    expect(screen.getByTestId("topic-distribution-chart")).toBeVisible();
    await user.click(within(views).getByRole("button", { name: "关键词词云" }));
    expect(screen.getByTestId("topic-word-cloud")).toBeVisible();
    await user.click(within(views).getByRole("button", { name: "主题清单" }));
    expect(screen.getByTestId("topic-table")).toBeVisible();
    expect(getTopicsOverviewTabMock).toHaveBeenCalledWith("novel-1", "task-1");
    expect(getTopicSeriesMock).not.toHaveBeenCalled();
    expect(getTopicShiftsMock).not.toHaveBeenCalled();
  });

  it("诊断主题标签为空时仍渲染主内容而不是空白主体区", async () => {
    getTopicsOverviewTabMock.mockResolvedValue({
      run_id: "task-1",
      model: null,
      topics: [{ topic_id: 0, words: ["修炼"], weight: 0.8 }],
      distribution: [{ topic_id: 0, weight: 1 }],
      chapters: [],
      keywords: [],
      topic_labels: null,
      unavailable_reason: null,
      keyword_unavailable_reason: "no_cooccurrence: 过滤停用词后无可建图词元",
    });

    renderTopicsPage();

    const user = userEvent.setup();
    await user.click(await screen.findByRole("tab", { name: "完整主题分布" }));
    expect(await screen.findByTestId("topic-bar-chart")).toBeVisible();
    const views = screen.getByRole("group", { name: "主题分布视图" });
    await user.click(within(views).getByRole("button", { name: "关键词词云" }));
    expect(screen.getByTestId("topic-word-cloud")).toBeVisible();
    await user.click(within(views).getByRole("button", { name: "主题清单" }));
    expect(screen.getByTestId("topic-table")).toBeVisible();
  });

  it("主题固定工作区保留全部业务页签和独立端点", async () => {
    getTopicsOverviewTabMock.mockResolvedValue({
      run_id: "task-1",
      model: null,
      topics: [],
      distribution: null,
      chapters: [],
      keywords: [],
      topic_labels: null,
      unavailable_reason: "unavailable",
      keyword_unavailable_reason: null,
    });

    renderTopicsPage();

    await screen.findByTestId("tab-unavailable-state");
    const user = userEvent.setup();
    await user.click(screen.getByRole("tab", { name: "完整主题分布" }));
    await user.click(screen.getByRole("tab", { name: "主题演进" }));
    await user.click(screen.getByRole("tab", { name: "主题迁移" }));
    await user.click(screen.getByRole("tab", { name: "主题情绪" }));

    expect(screen.getByRole("tab", { name: "主题总览" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "完整主题分布" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "主题演进" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "主题迁移" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "主题情绪" })).toBeInTheDocument();
    expect(getTopicSeriesMock).toHaveBeenCalledWith("novel-1", "task-1");
    expect(getTopicShiftsMock).toHaveBeenCalledWith("novel-1", "task-1");
    expect(getTopicEmotionMock).toHaveBeenCalledWith("novel-1", "task-1");
  });

  it("renders analysis-not-complete state for running tasks", async () => {
    const notCompleteError = {
      isAxiosError: true,
      response: {
        status: 400,
        data: {
          detail: "分析未完成，当前状态: running",
          error_type: "AnalysisNotCompleteError",
          status_code: 400,
        },
      },
    };
    getTopicsOverviewTabMock.mockRejectedValue(notCompleteError);
    getTopicSeriesMock.mockRejectedValue(notCompleteError);
    getTopicShiftsMock.mockRejectedValue(notCompleteError);
    getTopicEmotionMock.mockRejectedValue(notCompleteError);

    renderTopicsPage();

    expect(await screen.findByText("主题结果尚未完成")).toBeInTheDocument();
    expect(screen.getByText("当前任务仍在分析中，主题结果暂时不可读，请等待任务进入完成态后再查看。")).toBeInTheDocument();
  });
});
