import { createElement } from "react";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

vi.mock("@/components/charts/CharacterRankingBar", () => ({
  CharacterRankingBar: passthroughComponent("character-ranking-bar"),
}));

vi.mock("@/components/charts/RoleFunctionPie", () => ({
  RoleFunctionPie: passthroughComponent("role-function-pie"),
}));

vi.mock("@/components/characters/CharacterTable", () => ({
  CharacterTable: passthroughComponent("character-table"),
}));

vi.mock("@/components/characters/FocusCastCard", () => ({
  FocusCastCard: passthroughComponent("focus-cast-card"),
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

  it("排行/角色表 tab 走 /characters，功能与焦点 tab 走专用端点", async () => {
    getCharactersMock.mockResolvedValue([
      {
        name: "沈砚",
        appearance_count: 12,
        dominant_role_function: "protagonist",
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

    expect(await screen.findByTestId("character-ranking-bar")).toBeInTheDocument();
    expect(getCharactersMock).toHaveBeenCalledWith("novel-1", "task-1");
    expect(getCharacterFunctionTabMock).toHaveBeenCalledWith("novel-1", "task-1");
  });

  it("功能与焦点切片为空值时仍渲染排行主内容", async () => {
    const user = userEvent.setup();
    getCharactersMock.mockResolvedValue([
      {
        name: "沈砚",
        appearance_count: 12,
        dominant_role_function: "protagonist",
      },
    ]);

    renderCharactersPage();

    expect(await screen.findByTestId("character-ranking-bar")).toBeInTheDocument();
    expect(screen.queryByTestId("focus-cast-card")).not.toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "功能与焦点" }));

    expect(await screen.findByTestId("focus-cast-card")).toBeInTheDocument();
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
