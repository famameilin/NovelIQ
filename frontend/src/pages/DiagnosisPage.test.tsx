import { createElement } from "react";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DiagnosisPage } from "@/pages/DiagnosisPage";
import { useNovelStore } from "@/store/novelStore";

const getDiagnosisMock = vi.fn();
const getForeshadowingThreadsMock = vi.fn();

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
  getDiagnosis: (...args: unknown[]) => getDiagnosisMock(...args),
  getForeshadowingThreads: (...args: unknown[]) => getForeshadowingThreadsMock(...args),
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

vi.mock("@/components/common/ScoreCard", () => ({
  ScoreCard: (props: { title: string }) => <div>{props.title}</div>,
}));

vi.mock("@/components/diagnosis/DiagnosisHeader", () => ({
  DiagnosisHeader: passthroughComponent("diagnosis-header"),
}));

vi.mock("@/components/diagnosis/DiagnosisText", () => ({
  DiagnosisText: passthroughComponent("diagnosis-text"),
}));

vi.mock("@/components/diagnosis/ValueLogicCard", () => ({
  ValueLogicCard: passthroughComponent("value-logic-card"),
}));

vi.mock("@/components/diagnosis/TopicLabels", () => ({
  TopicLabels: passthroughComponent("topic-labels"),
}));

vi.mock("@/components/diagnosis/CharacterCastCard", () => ({
  CharacterCastCard: passthroughComponent("character-cast-card"),
}));

vi.mock("@/components/charts/ArcScoresChart", () => ({
  ArcScoresChart: passthroughComponent("arc-scores-chart"),
}));

vi.mock("@/components/ui/card", () => ({
  Card: passthroughComponent("card"),
  CardContent: passthroughComponent("card-content"),
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

function renderDiagnosisPage() {
  const queryClient = createQueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <DiagnosisPage />
    </QueryClientProvider>,
  );
}

describe("DiagnosisPage", () => {
  beforeEach(() => {
    currentNovelId = "novel-1";
    currentSearchParams = "task_id=task-1";
    getDiagnosisMock.mockReset();
    getForeshadowingThreadsMock.mockReset();
    useNovelStore.getState().clear();
  });

  it("renders a stable empty state when diagnosis returns null", async () => {
    getDiagnosisMock.mockResolvedValue(null);
    getForeshadowingThreadsMock.mockResolvedValue([]);

    renderDiagnosisPage();

    expect(await screen.findByText("诊断报告暂未生成")).toBeInTheDocument();
    expect(screen.getByText("当前任务暂时还没有可展示的诊断结果。")).toBeInTheDocument();
  });

  it("shows a visible warning when foreshadowing thread drill-down fails", async () => {
    getDiagnosisMock.mockResolvedValue({
      narrative_type: "寓言",
      foreshadow_expectation: 0.42,
      topic_labels: ["成长"],
    });
    getForeshadowingThreadsMock.mockRejectedValue(new Error("threads boom"));

    renderDiagnosisPage();

    expect(await screen.findByText("伏笔回收预期")).toBeInTheDocument();
    expect(await screen.findByText("Setup 台账加载失败")).toBeInTheDocument();
    expect(screen.getByText("伏笔 setup 台账暂时无法读取，请稍后重试。")).toBeInTheDocument();
  });
});
