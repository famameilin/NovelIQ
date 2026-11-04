import { describe, expect, it } from "vitest";
import { formatWordCount } from "./utils";

describe("formatWordCount", () => {
  it("一万以内展示完整数字并加千分位", () => {
    expect(formatWordCount(0)).toBe("0 字");
    expect(formatWordCount(8764)).toBe("8,764 字");
    expect(formatWordCount(9999)).toBe("9,999 字");
  });

  it("一万到一亿之间换算成万字", () => {
    expect(formatWordCount(10_000)).toBe("1.0 万字");
    expect(formatWordCount(123_456)).toBe("12.3 万字");
    expect(formatWordCount(99_999_999)).toBe("10000.0 万字");
  });

  it("一亿以上换算成亿字", () => {
    expect(formatWordCount(100_000_000)).toBe("1.0 亿字");
    expect(formatWordCount(123_456_789)).toBe("1.2 亿字");
  });
});
