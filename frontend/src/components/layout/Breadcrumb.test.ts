import { describe, expect, it } from "vitest";

import { getBreadcrumbLabel } from "@/components/layout/Breadcrumb";

describe("getBreadcrumbLabel", () => {
  it("返回语言特征页的中文名称", () => {
    expect(getBreadcrumbLabel("/linguistic")).toBe("语言特征");
  });
  it("分析任务地址显示业务名称",()=>{
    expect(getBreadcrumbLabel('/analysis/task-identity')).toBe('分析任务详情');
  });
});
