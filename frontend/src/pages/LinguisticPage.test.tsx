import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { LinguisticPage } from "@/pages/LinguisticPage";
import { useNovelStore } from "@/store/novelStore";

const getLinguisticFeaturesMock = vi.fn();
const getLinguisticEntitiesTabMock = vi.fn();
const getLinguisticWord2vecMock = vi.fn();

let currentNovelId = "novel-1";
let currentSearchParams = "task_id=task-1";

function passthroughComponent(displayName: string) {
  const Component = ({ children }: { children?: ReactNode }) => <div data-testid={displayName}>{children}</div>;
  Component.displayName = displayName;
  return Component;
}

vi.mock("react-router-dom", () => ({
  useNavigate: () => vi.fn(),
  useParams: () => ({ novelId: currentNovelId }),
  useSearchParams: () => [new URLSearchParams(currentSearchParams)],
}));

vi.mock("@/api/linguistic", () => ({
  getLinguisticFeatures: (...args: unknown[]) => getLinguisticFeaturesMock(...args),
  getLinguisticWord2vec: (...args: unknown[]) => getLinguisticWord2vecMock(...args),
}));

vi.mock("@/api/tabs", () => ({
  getLinguisticEntitiesTab: (...args: unknown[]) => getLinguisticEntitiesTabMock(...args),
  tabQueryKey: (tab: string, novelId: string | undefined, taskId: string | null, ...rest: unknown[]) =>
    ["tabs", novelId, taskId, tab, ...rest],
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

vi.mock("@/components/layout/PageContainer", () => ({
  PageContainer: passthroughComponent("page-container"),
}));

vi.mock("@/components/common/NovelHeader", () => ({
  NovelHeader: (props: { title: string }) => <div>{props.title}</div>,
}));

vi.mock("@/components/common/AnalysisNotCompleteState", () => ({
  AnalysisNotCompleteState: (props: { title?: string; description?: string }) => (
    <div data-testid="analysis-not-complete-state">
      <p>{props.title}</p>
      <p>{props.description}</p>
    </div>
  ),
}));

vi.mock("@/components/linguistic/RatioBarChart", () => ({
  RatioBarChart: passthroughComponent("ratio-bar-chart"),
}));

vi.mock("@/components/linguistic/PosSimilarityHeatmap", () => ({
  PosSimilarityHeatmap: passthroughComponent("pos-similarity-heatmap"),
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

function renderLinguisticPage() {
  const queryClient = createQueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <LinguisticPage />
    </QueryClientProvider>,
  );
}

describe("LinguisticPage", () => {
  beforeEach(() => {
    currentNovelId = "novel-1";
    currentSearchParams = "task_id=task-1";
    getLinguisticFeaturesMock.mockReset();
    getLinguisticEntitiesTabMock.mockReset();
    getLinguisticWord2vecMock.mockReset();
    getLinguisticFeaturesMock.mockResolvedValue({
      run_id: "task-1",
      paragraph_count: 420,
      token_total: 72000,
      sentence_total: 4800,
      word_length_ratios: { 1: 0.18, 2: 0.46 },
      pos_ratios: { noun: 0.32, verb: 0.21 },
      sentence_pattern_ratios: { short: 0.42, medium: 0.31 },
      avg_dependency_depth: 2.84,
      max_dependency_depth: 9,
      dependency_relation_ratios: { HED: 0.18, SBV: 0.24 },
      dependency_root_count: 4800,
      boundary_pos_score_sum: 14.27,
      boundary_neg_score_sum: 2447.93,
      chapters: [],
      unavailable_reason: null,
    });
    getLinguisticEntitiesTabMock.mockResolvedValue({
      run_id: "task-1",
      count_by_type: { person: 186 },
      surface_top: [{ surface_text: "林渡", entity_type: "person", count: 92 }],
      total_char_count: 186000,
      metric_hit_count: 0,
      fixed_phrase_density: 0,
      four_char_candidate_count: 12,
      total_hits: 59,
      unavailable_reason: null,
    });
    getLinguisticWord2vecMock.mockResolvedValue({
      run_id: "task-1",
      model: { embedding_dimension: 300, vocabulary_size: 48210, artifact_scope: "pretrained_finetuned" },
      pos_coverage: [{ pos_group: "noun", source_token_total: 7680, in_vocabulary_token_total: 7104, coverage_ratio: 0.925 }],
      pos_centroids: [
        { pos_group: "noun", weighted_token_total: 7680, embedding_vector: [1, 0] },
        { pos_group: "verb", weighted_token_total: 5040, embedding_vector: [0, 1] },
      ],
      pos_similarity_matrix: [
        [1, 0],
        [0, 1],
      ],
      unavailable_reason: null,
    });
    useNovelStore.getState().clear();
  });

  it("表达结构、实体与短语、词汇与语义页签分别保留三个聚合端点", async () => {
    renderLinguisticPage();

    expect((await screen.findAllByTestId("ratio-bar-chart")).length).toBeGreaterThanOrEqual(1);
    expect(getLinguisticFeaturesMock).toHaveBeenCalledWith("novel-1", "task-1");
    expect(getLinguisticEntitiesTabMock).toHaveBeenCalledWith("novel-1", "task-1");
    expect(getLinguisticWord2vecMock).toHaveBeenCalledWith("novel-1", "task-1");
  });

  it("在固定工作区页签间切换，并保留实体和词向量详情", async () => {
    renderLinguisticPage();

    expect(await screen.findByRole("tab", { name: "表达结构" })).toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(screen.getByRole("tab", { name: "实体与短语" }));

    expect(await screen.findByText("高频实体名（前 20 名）")).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "词汇与语义" }));

    expect(screen.getByText("预训练微调词向量")).toBeInTheDocument();
    expect(screen.getByText(/92\.5%/)).toBeInTheDocument();
    expect(screen.getAllByText(/加权词元/).length).toBeGreaterThan(0);
    expect(screen.queryByText("run-id")).not.toBeInTheDocument();
  });

  it("语言阶段未运行时展示 unavailable_reason 空态", async () => {
    getLinguisticFeaturesMock.mockResolvedValue({
      run_id: "task-1",
      paragraph_count: 0,
      token_total: null,
      sentence_total: null,
      word_length_ratios: null,
      pos_ratios: null,
      sentence_pattern_ratios: null,
      avg_dependency_depth: null,
      max_dependency_depth: null,
      dependency_relation_ratios: null,
      dependency_root_count: null,
      boundary_pos_score_sum: null,
      boundary_neg_score_sum: null,
      chapters: [],
      unavailable_reason: "linguistic_unavailable: 无 paragraph_linguistic_features 行（语言阶段未运行）",
    });

    renderLinguisticPage();

    expect(await screen.findByTestId("tab-unavailable-state")).toBeInTheDocument();
  });

  it("表达结构指标条展示句级监督边界两列，未拟合时回退占位符", async () => {
    renderLinguisticPage();

    expect(await screen.findByText("边界正向分和")).toBeInTheDocument();
    expect(screen.getByText("14.27")).toBeInTheDocument();
    expect(screen.getByText("2447.93")).toBeInTheDocument();

    getLinguisticFeaturesMock.mockResolvedValue({
      run_id: "task-1",
      paragraph_count: 420,
      token_total: 72000,
      sentence_total: 4800,
      word_length_ratios: { 1: 0.18 },
      pos_ratios: { noun: 0.32 },
      sentence_pattern_ratios: { short: 0.42 },
      avg_dependency_depth: 2.84,
      max_dependency_depth: 9,
      dependency_relation_ratios: { HED: 0.18 },
      dependency_root_count: 4800,
      boundary_pos_score_sum: null,
      boundary_neg_score_sum: null,
      chapters: [],
      unavailable_reason: null,
    });
    renderLinguisticPage();

    expect(await screen.findAllByText("边界负向分和").then((nodes) => nodes.length)).toBeGreaterThanOrEqual(1);
    expect((await screen.findAllByText("—")).length).toBeGreaterThan(0);
  });
});
