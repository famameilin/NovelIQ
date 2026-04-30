import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TopicWordCloud } from "./TopicWordCloud";
import type { Topic } from "@/api/types";

let mockedLayoutWords: Array<Record<string, unknown>> = [];
const mockInViewRef: { current: HTMLDivElement | null } = { current: null };

vi.mock("@/hooks/useInView", () => ({
  useInView: () => ({ ref: mockInViewRef, isVisible: true }),
}));

vi.mock("@/hooks/useChartThemeSignature", () => ({
  useChartThemeSignature: () => "test-theme",
}));

vi.mock("@/lib/theme", () => ({
  getCSSColorVar: (token: string) => `mock-${token}`,
}));

vi.mock("d3-cloud", () => ({
  default: () => {
    let endHandler: ((words: Array<Record<string, unknown>>) => void) | null = null;

    return {
      size() {
        return this;
      },
      words(words: Array<Record<string, unknown>>) {
        mockedLayoutWords = words;
        return this;
      },
      padding() {
        return this;
      },
      rotate() {
        return this;
      },
      font() {
        return this;
      },
      fontSize() {
        return this;
      },
      random() {
        return this;
      },
      on(_eventName: "end", handler: (words: Array<Record<string, unknown>>) => void) {
        endHandler = handler;
        return this;
      },
      start() {
        endHandler?.(
          mockedLayoutWords.map((word, index) => ({
            ...word,
            x: index * 18,
            y: index * 12,
            rotate: 0,
          }))
        );
      },
      stop() {},
    };
  },
}));

/**
 * 2026-04-30，任务：为替换后的 TopicWordCloud 补定向测试
 * 新建原因：统一构造主题输入，覆盖重复词聚合和颜色映射场景
 */
function createTopics(): Topic[] {
  return [
    {
      topic_id: 0,
      label: "修炼线",
      weight: 0.8,
      words: ["成长", "修炼", "宗门"],
    },
    {
      topic_id: 1,
      label: "情感线",
      weight: 0.6,
      words: ["心动", "成长", "相遇"],
    },
  ];
}

describe("TopicWordCloud", () => {
  beforeEach(() => {
    mockedLayoutWords = [];
    mockInViewRef.current = null;
  });

  it("renders empty state when topics are missing", () => {
    render(<TopicWordCloud topics={[]} />);

    expect(screen.getByText("暂无关键词数据")).toBeInTheDocument();
  });

  it("keeps aggregated words, topic color mapping and tooltip semantics", async () => {
    render(<TopicWordCloud topics={createTopics()} maxWords={10} />);

    await screen.findByText("成长");

    expect(mockedLayoutWords).toHaveLength(5);

    const growthWord = mockedLayoutWords.find((word) => word.name === "成长");
    expect(growthWord).toMatchObject({
      topicId: 0,
      topicLabel: "修炼线",
    });

    const growthText = screen.getByText("成长");
    const heartText = screen.getByText("心动");

    expect(growthText.getAttribute("fill")).not.toBe(heartText.getAttribute("fill"));

    fireEvent.pointerMove(growthText, { clientX: 100, clientY: 120 });

    await waitFor(() => {
      expect(screen.getByText("所属: 修炼线")).toBeInTheDocument();
    });
  });
});
