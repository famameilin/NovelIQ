import { createElement } from "react";
import type { ReactNode } from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { FocusCastCard } from "@/components/characters/FocusCastCard";

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

vi.mock("framer-motion", () => ({
  motion: new Proxy(
    {},
    {
      get: (_target, key: string) => motionElement(key),
    },
  ),
}));

vi.mock("@/components/common/DashboardCardShell", () => ({
  DashboardCardShell: (props: { title: string; children?: ReactNode }) => (
    <section>
      <h2>{props.title}</h2>
      <div>{props.children}</div>
    </section>
  ),
}));

vi.mock("@/components/ui/badge", () => ({
  Badge: passthroughComponent("badge"),
}));

describe("FocusCastCard", () => {
  it("counts focus characters from the authoritative focus list", () => {
    render(
      <FocusCastCard
        focusStructure="dual"
        focusCharacters={["叶文洁", "汪淼"]}
        characters={[
          {
            name: "叶文洁",
            appearance_count: 12,
            dominant_role_function: "主体",
            narrative_focus_score: 0.81,
            is_focus_character: true,
            avg_emotion_score: 0.2,
          },
        ]}
        arcScores={{ 叶文洁: 9.2, 汪淼: 8.1 }}
      />,
    );

    expect(screen.getAllByText("叶文洁")).toHaveLength(2);
    expect(screen.getByText("汪淼")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByText("焦点人数")).toBeInTheDocument();
  });
});
