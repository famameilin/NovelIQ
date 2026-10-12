import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { CharacterCastCard } from "@/components/diagnosis/CharacterCastCard";

describe("CharacterCastCard", () => {
  it("小阵容直接展示三类人物，不把五人名单拆成多页", () => {
    render(<CharacterCastCard focusStructure="dual" focusCharacters={["甲", "乙"]}
      coreCast={["丙", "丁", "戊", "己", "庚"]} majorCast={["辛"]} />);

    expect(screen.getByText("双主角")).toBeInTheDocument();
    expect(screen.getByText("主要角色")).toBeInTheDocument();
    expect(screen.getByText("庚")).toBeInTheDocument();
    expect(screen.getByText("辛")).toBeInTheDocument();
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
  });

  it("五百人名单每组仅展示十二人，搜索与分页均能访问后续人物", async () => {
    const user = userEvent.setup();
    render(<CharacterCastCard focusCharacters={["焦点人物"]}
      coreCast={Array.from({ length: 500 }, (_, index) => `角色${String(index + 1).padStart(3, "0")}`)} majorCast={["主要人物"]} />);

    expect(screen.getByText("500 人")).toBeInTheDocument();
    expect(screen.getByText("角色012")).toBeInTheDocument();
    expect(screen.queryByText("角色013")).not.toBeInTheDocument();
    const pagination = screen.getByRole("navigation", { name: "核心角色分页" });
    await user.click(within(pagination).getByRole("button", { name: "下一页" }));
    expect(screen.getByText("角色024")).toBeInTheDocument();
    expect(screen.queryByText("角色001")).not.toBeInTheDocument();
    expect(screen.getByText("焦点人物")).toBeInTheDocument();
    expect(screen.getByText("主要人物")).toBeInTheDocument();

    const search = screen.getByRole("textbox", { name: "核心角色姓名搜索" });
    await user.type(search, "角色500");
    expect(screen.getByText("角色500")).toBeInTheDocument();
    expect(screen.getByText("匹配 1 / 500 人")).toBeInTheDocument();
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
    await user.clear(search);
    expect(screen.getByText("角色001")).toBeInTheDocument();
    await user.type(search, "不存在");
    expect(screen.getByText("未找到匹配角色")).toBeInTheDocument();
  });
});
