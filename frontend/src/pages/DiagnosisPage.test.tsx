import { createElement } from "react";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DiagnosisPage } from "@/pages/DiagnosisPage";
import { useNovelStore } from "@/store/novelStore";

const getDiagnosisMock = vi.fn();
const getForeshadowingTreesMock = vi.fn();

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
  getForeshadowingTrees: (...args: unknown[]) => getForeshadowingTreesMock(...args),
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
    getForeshadowingTreesMock.mockReset();
    useNovelStore.getState().clear();
  });

  it("renders a stable empty state when diagnosis returns null", async () => {
    getDiagnosisMock.mockResolvedValue(null);
    getForeshadowingTreesMock.mockResolvedValue([]);

    renderDiagnosisPage();

    expect(await screen.findByText("诊断报告暂未生成")).toBeInTheDocument();
    expect(screen.getByText("当前任务暂时还没有可展示的诊断结果。")).toBeInTheDocument();
  });

  it("still renders foreshadowing tracking when diagnosis returns null but threads are available", async () => {
    getDiagnosisMock.mockResolvedValue(null);
    getForeshadowingTreesMock.mockResolvedValue([
      {
        root_event_id: "root-1",
        tree_id: "tree-1",
        first_chapter_id: 3,
        last_chapter_id: 8,
        anchor_chapter_ids: [3, 8],
        description: "铜铃异响反复指向山门旧案",
        expected_payoff_family: "真相揭露",
        payoff_likelihood: "high",
        strength: "high",
        status: "reinforced",
        active: true,
        latest_reason: "再次强化旧案关联",
      },
    ]);

    renderDiagnosisPage();

    expect(await screen.findByText("诊断报告暂未生成")).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("tab", { name: "伏笔追踪" }));
    expect(screen.getAllByText("铜铃异响反复指向山门旧案").length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText(/setup/i)).not.toBeInTheDocument();
  });

  it("shows a visible warning when foreshadowing thread drill-down fails", async () => {
    getDiagnosisMock.mockResolvedValue(null);
    getForeshadowingTreesMock.mockRejectedValue(new Error("threads boom"));

    renderDiagnosisPage();

    expect(await screen.findByText("伏笔追踪加载失败")).toBeInTheDocument();
    expect(screen.getByText("伏笔线索暂时无法读取，请稍后重试。")).toBeInTheDocument();
  });

  it("renders diagnosis cards when optional focus fields are absent", async () => {
    getDiagnosisMock.mockResolvedValue({
      genre_labels: ["科幻"],
      style_labels: ["硬核"],
      foreshadow_expectation: 0.42,
      topic_labels: ["成长"],
    });
    getForeshadowingTreesMock.mockResolvedValue([]);

    renderDiagnosisPage();

    expect(await screen.findByText("伏笔回收预期")).toBeInTheDocument();
    expect(screen.getByTestId("diagnosis-header")).toBeInTheDocument();
    expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
      "综合概览",
      "价值主题",
      "角色结构",
      "伏笔追踪",
    ]);
  });

  it("renders analysis-not-complete state for running tasks", async () => {
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
    getForeshadowingTreesMock.mockRejectedValue({
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

    renderDiagnosisPage();

    expect(await screen.findByText("诊断结果尚未完成")).toBeInTheDocument();
    expect(screen.getByText("当前任务仍在分析中，诊断报告和伏笔追踪暂时不可读，请等待任务进入完成态后再查看。")).toBeInTheDocument();
  });

  it("切换伏笔追踪后支持三态筛选、章节轨迹和详情指标", async () => {
    const user = userEvent.setup();
    getDiagnosisMock.mockResolvedValue({
      genre_labels: ["悬疑"],
      style_labels: ["冷峻"],
      foreshadow_expectation: 0.62,
      diagnosis: "线索逐步收束",
    });
    getForeshadowingTreesMock.mockResolvedValue([
      {
        root_event_id: "root-open",
        tree_id: "tree-open",
        first_chapter_id: 2,
        last_chapter_id: 4,
        anchor_chapter_ids: [2, 4],
        description: "开放线索",
        expected_payoff_family: "规则揭示",
        payoff_likelihood: "medium",
        strength: "medium",
        status: "open",
        active: true,
        latest_reason: "等待后续证据",
      },
      {
        root_event_id: "root-reinforced",
        tree_id: "tree-reinforced",
        first_chapter_id: 3,
        last_chapter_id: 8,
        anchor_chapter_ids: [3, 5, 8],
        description: "铜铃异响反复指向山门旧案",
        expected_payoff_family: "真相揭露",
        payoff_likelihood: "high",
        strength: "high",
        status: "reinforced",
        active: true,
        latest_reason: "最近一章再次强化旧案关联",
        latest_why_unresolved_now: "关键证人尚未现身",
      },
      {
        root_event_id: "root-paid",
        tree_id: "tree-paid",
        first_chapter_id: 6,
        last_chapter_id: 10,
        anchor_chapter_ids: [6, 10],
        description: "已回收线索",
        expected_payoff_family: "身份揭示",
        payoff_likelihood: "high",
        strength: "high",
        status: "likely_paid_off",
        active: true,
        latest_reason: "身份已经得到解释",
      },
    ]);

    renderDiagnosisPage();

    await user.click(await screen.findByRole("tab", { name: "伏笔追踪" }));
    expect(screen.getByRole("tab", { name: "伏笔追踪", selected: true })).toBeInTheDocument();
    const filterGroup = screen.getByRole("group", { name: "伏笔状态筛选" });
    expect(within(filterGroup).getByRole("button", { name: "待回收" })).toBeInTheDocument();
    expect(within(filterGroup).getByRole("button", { name: "持续强化" })).toBeInTheDocument();
    expect(within(filterGroup).getByRole("button", { name: "疑似回收" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /铜铃异响反复指向山门旧案/ }));
    expect(screen.getByText("第 3 章 · 首次出现")).toBeInTheDocument();
    expect(screen.getByText("第 5 章 · 再次出现")).toBeInTheDocument();
    expect(screen.getByText("第 8 章 · 最近出现")).toBeInTheDocument();
    expect(screen.getByText("最近一章再次强化旧案关联")).toBeInTheDocument();
    expect(screen.queryByText("high")).not.toBeInTheDocument();
    expect(screen.queryByText("reinforced")).not.toBeInTheDocument();

    await user.click(within(filterGroup).getByRole("button", { name: "持续强化" }));
    expect(screen.getAllByText("铜铃异响反复指向山门旧案").length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText("开放线索")).not.toBeInTheDocument();

    await user.click(screen.getByText("分析详情"));
    expect(screen.getByText("线索强度")).toBeInTheDocument();
    expect(screen.queryByText("判断置信度")).not.toBeInTheDocument();
  });
});
