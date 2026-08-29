import { createElement } from "react";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
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
  TopicBarChart: passthroughComponent("topic-bar-chart"),
  TopicTable: passthroughComponent("topic-table"),
  TopicDistributionChart: passthroughComponent("topic-distribution-chart"),
  TopicKeywordsCard: passthroughComponent("topic-keywords-card"),
  TopicSeriesChart: passthroughComponent("topic-series-chart"),
  TopicShiftsPanel: passthroughComponent("topic-shifts-panel"),
  TopicEmotionPanel: passthroughComponent("topic-emotion-panel"),
}));

vi.mock("@/components/ui/button", () => ({
  Button: passthroughComponent("button"),
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

  it("总览 tab 走 /tabs/topics-overview 并渲染词云与分布", async () => {
    getTopicsOverviewTabMock.mockResolvedValue({
      run_id: "task-1",
      model: null,
      topics: [{ topic_id: 0, words: ["修炼", "成长"], weight: 0.8 }],
      distribution: [{ topic_id: 0, weight: 1 }],
      chapters: [],
      keywords: [{ word: "宗门", score: 0.08 }],
      topic_labels: ["成长"],
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

    expect(await screen.findByTestId("topic-word-cloud")).toBeInTheDocument();
    expect(screen.getByTestId("topic-distribution-chart")).toBeInTheDocument();
    expect(screen.getByTestId("topic-keywords-card")).toBeInTheDocument();
    expect(getTopicsOverviewTabMock).toHaveBeenCalledWith("novel-1", "task-1");
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

    expect(await screen.findByTestId("topic-word-cloud")).toBeInTheDocument();
    expect(screen.getByTestId("topic-bar-chart")).toBeInTheDocument();
    expect(screen.getByTestId("topic-table")).toBeInTheDocument();
  });

  it("演进/迁移/情绪 tab 各自走独立端点", async () => {
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

    const unavailableStates = await screen.findAllByTestId("tab-unavailable-state");
    expect(unavailableStates.length).toBeGreaterThanOrEqual(1);
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

    const notCompleteTitles = await screen.findAllByText("主题结果尚未完成");
    expect(notCompleteTitles.length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("当前任务仍在分析中，主题结果暂时不可读，请等待任务进入完成态后再查看。").length).toBeGreaterThanOrEqual(1);
  });
});
