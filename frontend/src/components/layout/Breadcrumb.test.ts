import { describe, expect, it } from "vitest";

import { getBreadcrumbLabel } from "@/components/layout/Breadcrumb";

describe("getBreadcrumbLabel", () => {
  it("返回语言特征页的中文名称", () => {
    expect(getBreadcrumbLabel("/linguistic")).toBe("语言特征");
  });
});
