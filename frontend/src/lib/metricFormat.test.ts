import { describe, expect, it } from "vitest";
import {
  formatNullableNumber,
  formatNullablePercent,
  formatProgressSpan,
  formatSampleInsufficient,
} from "@/lib/metricFormat";

describe("metricFormat", () => {
  it("可空数字在 null 和非有限值时显示样本不足", () => {
    expect(formatNullableNumber(null)).toBe("样本不足");
    expect(formatNullableNumber(undefined)).toBe("样本不足");
    expect(formatNullableNumber(Number.NaN)).toBe("样本不足");
    expect(formatNullableNumber(Number.POSITIVE_INFINITY)).toBe("样本不足");
  });

  it("保留零值并按单位格式化百分比和进度", () => {
    expect(formatNullableNumber(0)).toBe("0.00");
    expect(formatNullablePercent(0.125)).toBe("13%");
    expect(formatProgressSpan(0.125, 1)).toBe("全书 12.5%");
  });

  it("允许调用方提供缺失文案", () => {
    expect(formatNullableNumber(null, 2, "缺少有效章节")).toBe("缺少有效章节");
    expect(formatSampleInsufficient()).toBe("样本不足");
  });
});

