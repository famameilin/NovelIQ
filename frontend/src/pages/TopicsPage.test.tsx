import { createElement } from "react";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TopicsPage } from "@/pages/TopicsPage";
import { useNovelStore } from "@/store/novelStore";

const getTopicsMock = vi.fn();
const getDiagnosisMock = vi.fn();
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
  getTopics: (...args: unknown[]) => getTopicsMock(...args),
  getDiagnosis: (...args: unknown[]) => getDiagnosisMock(...args),
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

vi.mock("@/components/topics", () => ({
  TopicWordCloud: passthroughComponent("topic-word-cloud"),
  TopicBarChart: passthroughComponent("topic-bar-chart"),
  TopicTable: passthroughComponent("topic-table"),
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
    getTopicsMock.mockReset();
    getDiagnosisMock.mockReset();
    useNovelStore.getState().clear();
  });

  it("renders rerun-required state when diagnosis contract is invalid", async () => {
    getTopicsMock.mockResolvedValue([
      { topic_id: 0, words: ["修炼", "成长"], weight: 0.8 },
    ]);
    getDiagnosisMock.mockResolvedValue({
      rerun_required: true,
      rerun_reason: "focus_contract_incomplete",
    });

    renderTopicsPage();

    expect(await screen.findByText("主题结果需要重跑")).toBeInTheDocument();
    expect(
      screen.getByText("当前任务的 diagnosis 焦点合同已失效，主题命名结果不再可信，请重新分析后再查看主题页。"),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("topic-word-cloud")).not.toBeInTheDocument();
  });

  it("renders analysis-not-complete state for running tasks", async () => {
    getTopicsMock.mockRejectedValue({
      isAxiosError: true,
      response: {
        status: 400,
        data: {
          detail: "分析未完成，当前状态: running",
          error_type: "AnalysisNotCompleteError",
          status_code: 400,
        },
      },
    });
    getDiagnosisMock.mockRejectedValue({
      isAxiosError: true,
      response: {
        status: 400,
        data: {
          detail: "分析未完成，当前状态: running",
          error_type: "AnalysisNotCompleteError",
          status_code: 400,
        },
      },
    });

    renderTopicsPage();

    expect(await screen.findByText("主题结果尚未完成")).toBeInTheDocument();
    expect(screen.getByText("当前任务仍在分析中，主题结果暂时不可读，请等待任务进入完成态后再查看。")).toBeInTheDocument();
  });
});
