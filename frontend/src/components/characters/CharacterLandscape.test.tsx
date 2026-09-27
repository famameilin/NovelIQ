import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Character } from "@/api/types";
import { CharacterLandscape } from "@/components/characters/CharacterLandscape";

describe("CharacterLandscape", () => {
  it("排行分页保留所有角色的入口", async () => {
    const user = userEvent.setup();
    const characters: Character[] = Array.from({ length: 8 }, (_, index) => ({
      name: `角色${index + 1}`,
      appearance_count: 8 - index,
      dominant_role_function: "protagonist",
    }));
    const onSelectName = vi.fn();
    render(<CharacterLandscape characters={characters} focusCharacters={[]} view="ranking" sortMode="appearance"
      selectedName={null} onSortModeChange={vi.fn()} onSelectName={onSelectName} />);

    const controls = screen.getByRole("navigation", { name: "角色排行分页" });
    expect(screen.getByText("角色1")).toBeInTheDocument();
    expect(screen.queryByText("角色7")).not.toBeInTheDocument();
    await user.click(within(controls).getByRole("button", { name: "下一页" }));
    expect(screen.getByText("角色7")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /角色7/ }));
    expect(onSelectName).toHaveBeenCalledWith("角色7");
  });
});
