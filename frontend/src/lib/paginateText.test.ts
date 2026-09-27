import { describe, expect, it } from "vitest";
import { paginateText } from "@/lib/paginateText";

describe("paginateText", () => {
  it("长段落分页后不丢失句子、换行或末尾文本", () => {
    const text = `第一句。${"长段".repeat(130)}\n第二段；最后一句！`;
    const pages = paginateText(text, 80);
    expect(pages.length).toBeGreaterThan(1);
    expect(pages.every((page) => page.length <= 80)).toBe(true);
    expect(pages.join("")).toBe(text);
  });
});
