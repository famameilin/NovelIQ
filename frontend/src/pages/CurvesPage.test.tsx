import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";

import { CurvesPage } from "@/pages/CurvesPage";
import { TooltipProvider } from "@/components/ui/tooltip";

const getEmotionTrend = vi.fn().mockResolvedValue([]);
const getRhythmTab = vi.fn().mockResolvedValue({ curves: [], narrative_structure: null });
const navigate = vi.fn();

vi.mock("react-router-dom", () => ({
  useParams: () => ({ novelId: "novel-1" }),
  useSearchParams: () => [new URLSearchParams("task_id=task-1")],
  useNavigate: () => navigate,
}));
vi.mock("@/hooks/useNovelScopedTask", () => ({
  useNovelScopedTask: () => ({ storeTaskId: "task-1", urlTaskSyncRef: { current: null } }),
  shouldWriteBackTaskUrl: () => false,
}));
vi.mock("@/api/results", () => ({ getEmotionTrend: (...args: unknown[]) => getEmotionTrend(...args) }));
vi.mock("@/api/tabs", () => ({
  getRhythmTab: (...args: unknown[]) => getRhythmTab(...args),
  tabQueryKey: (...args: unknown[]) => args,
}));
vi.mock("@/api/novels", () => ({ getNovel: () => Promise.resolve({ title: "测试小说" }) }));
vi.mock("@/components/common/NovelHeader", () => ({ NovelHeader: ({ title }: { title: string }) => <h1>{title}</h1> }));
vi.mock("@/components/charts/EmotionTrendChart", () => ({ EmotionTrendChart: () => <div>情绪图</div> }));
vi.mock("@/components/charts/RhythmCurveChart", () => ({ RhythmCurveChart: () => <div>节奏图</div> }));

it("先加载情绪趋势，切换到节奏张力后再请求对应数据", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><TooltipProvider><CurvesPage /></TooltipProvider></QueryClientProvider>);

  await waitFor(() => expect(getEmotionTrend).toHaveBeenCalled());
  expect(getRhythmTab).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("tab", { name: "节奏张力" }));
  await waitFor(() => expect(getRhythmTab).toHaveBeenCalledWith("novel-1", "task-1", { maxPoints: 800 }));
  expect(screen.getByRole("tab", { name: "节奏张力" })).toHaveAttribute("aria-selected", "true");
});
