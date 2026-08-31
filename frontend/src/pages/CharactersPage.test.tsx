import { createElement } from "react";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CharactersPage } from "@/pages/CharactersPage";
import { useNovelStore } from "@/store/novelStore";

const getCharactersMock = vi.fn();
const getCharacterFunctionTabMock = vi.fn();

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
  getCharacters: (...args: unknown[]) => getCharactersMock(...args),
}));

vi.mock("@/api/tabs", () => ({
  getCharacterFunctionTab: (...args: unknown[]) => getCharacterFunctionTabMock(...args),
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

function renderCharactersPage() {
  const queryClient = createQueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <CharactersPage />
    </QueryClientProvider>,
  );
}

describe("CharactersPage", () => {
  beforeEach(() => {
    currentNovelId = "novel-1";
    currentSearchParams = "task_id=task-1";
    getCharactersMock.mockReset();
    getCharacterFunctionTabMock.mockReset();
    getCharactersMock.mockResolvedValue([]);
    getCharacterFunctionTabMock.mockResolvedValue({
      run_id: "task-1",
      characters: [],
      focus_structure: null,
      focus_characters: null,
      arc_scores: null,
    });
    useNovelStore.getState().clear();
  });

  it("单文档流保留角色排行、功能焦点和角色表数据源", async () => {
    getCharactersMock.mockResolvedValue([
      {
        name: "沈砚",
        appearance_count: 12,
        dominant_role_function: "protagonist",
        dominant_role_ratio: 0.75,
        role_function_distribution: { protagonist: 0.75, helper: 0.25 },
        narrative_focus_score: 0.91,
        avg_emotion_score: 0.2,
        is_focus_character: true,
      },
    ]);
    getCharacterFunctionTabMock.mockResolvedValue({
      run_id: "task-1",
      characters: [],
      focus_structure: "single",
      focus_characters: ["沈砚"],
      arc_scores: { 沈砚: 8.2 },
    });

    renderCharactersPage();

    expect(await screen.findByText("综合角色榜")).toBeInTheDocument();
    expect(screen.getByText("角色功能构成")).toBeInTheDocument();
    expect(screen.getByText("单主角")).toBeInTheDocument();
    expect(screen.getByText("主导职责占比")).toBeInTheDocument();
    expect(screen.getByText("75.0%")).toBeInTheDocument();
    expect(screen.getByText("人物弧线 8.2")).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("protagonist");
    expect(document.body.textContent).not.toContain("single");
    expect(getCharactersMock).toHaveBeenCalledWith("novel-1", "task-1");
    expect(getCharacterFunctionTabMock).toHaveBeenCalledWith("novel-1", "task-1");
  });

  it("功能与焦点切片为空值时仍渲染角色文档流", async () => {
    getCharactersMock.mockResolvedValue([
      {
        name: "沈砚",
        appearance_count: 12,
        dominant_role_function: "protagonist",
      },
    ]);

    renderCharactersPage();

    expect(await screen.findByText("综合角色榜")).toBeInTheDocument();
    expect(screen.getByText("角色功能构成")).toBeInTheDocument();
    expect(screen.getByText("焦点人物")).toBeInTheDocument();
  });

  it("renders analysis-not-complete state for running tasks", async () => {
    getCharacterFunctionTabMock.mockRejectedValue({
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

    renderCharactersPage();

    expect(await screen.findByText("角色结果尚未完成")).toBeInTheDocument();
    expect(screen.getByText("当前任务仍在分析中，角色焦点结果暂时不可读，请等待任务进入完成态后再查看。")).toBeInTheDocument();
    expect(getCharactersMock).toHaveBeenCalledWith("novel-1", "task-1");
  });
});
