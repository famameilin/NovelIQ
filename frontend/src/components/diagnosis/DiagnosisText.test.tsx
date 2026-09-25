import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DiagnosisText } from "@/components/diagnosis/DiagnosisText";

describe("DiagnosisText", () => {
  it("将已知协议枚举和指标键转换为中文", () => {
    const source = "4 条伏笔全部open，主线 payoff_likelihood=high；rhythm_avg 0.574，std 0.017";

    render(<DiagnosisText diagnosisText={source} />);

    expect(
      screen.getByText("4 条伏笔全部待回收，主线 回收可能性较高；平均节奏 0.574，标准差 0.017"),
    ).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("payoff_likelihood");
    expect(document.body.textContent).not.toContain("rhythm_avg");
  });

  it("保留合法英文专名并按原有换行展示", () => {
    render(<DiagnosisText diagnosisText={"OpenAI 是作品中的机构名\n第二段保持中文"} />);

    expect(screen.getByText("OpenAI 是作品中的机构名")).toBeInTheDocument();
    expect(screen.getByText("第二段保持中文")).toBeInTheDocument();
  });
});
