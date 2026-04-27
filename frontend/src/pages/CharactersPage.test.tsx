import { createElement } from "react";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CharactersPage } from "@/pages/CharactersPage";
import { useNovelStore } from "@/store/novelStore";

const getCharactersMock = vi.fn();
const getDiagnosisMock = vi.fn();

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
    getDiagnosisMock.mockReset();
    useNovelStore.getState().clear();
  });

  it("renders rerun-required state when diagnosis focus contract is incomplete", async () => {
    getDiagnosisMock.mockResolvedValue({
      foreshadow_expectation: 0.42,
    });

    renderCharactersPage();

    expect(await screen.findByText("角色焦点结果需要重跑")).toBeInTheDocument();
    expect(
      screen.getByText("当前任务缺少完整的焦点结构合同，请重新分析后再查看角色焦点结果。"),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("character-ranking-bar")).not.toBeInTheDocument();
    expect(getCharactersMock).not.toHaveBeenCalled();
  });

  it("renders empty diagnosis state when diagnosis is still missing", async () => {
    getDiagnosisMock.mockResolvedValue(null);

    renderCharactersPage();

    expect(await screen.findByText("角色焦点结果暂未生成")).toBeInTheDocument();
    expect(screen.getByText("当前任务暂时还没有可展示的角色焦点结果。")).toBeInTheDocument();
    expect(getCharactersMock).not.toHaveBeenCalled();
  });
});
