import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { CharacterCastCard } from "@/components/diagnosis/CharacterCastCard";

describe("CharacterCastCard", () => {
  it("在单页中保留三类人物，并能翻到核心角色末项", async () => {
    const user = userEvent.setup();
    render(<CharacterCastCard focusStructure="dual" focusCharacters={["甲", "乙"]}
      coreCast={["丙", "丁", "戊", "己", "庚"]} majorCast={["辛"]} />);

    expect(screen.getByText("双主角")).toBeInTheDocument();
    expect(screen.getByText("主要角色")).toBeInTheDocument();
    expect(screen.queryByText("庚")).not.toBeInTheDocument();

    await user.click(within(screen.getByRole("navigation", { name: "核心角色分页" }))
      .getByRole("button", { name: "下一页" }));
    expect(screen.getByText("庚")).toBeInTheDocument();
    expect(screen.getByText("辛")).toBeInTheDocument();
  });
});
