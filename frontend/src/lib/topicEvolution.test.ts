import { describe, expect, it } from "vitest";
import { buildTopicEvolutionWindows } from "@/lib/topicEvolution";
import type { TopicSeriesPoint } from "@/api/types";

function point(start_position: number, token_count: number, weights: number[]): TopicSeriesPoint {
  return { paragraph_id: start_position, chapter_id: 1, chapter_sequence: 1, start_position, token_count, weights };
}

describe("buildTopicEvolutionWindows", () => {
  it("uses actual input token counts when aggregating paragraph weights", () => {
    const windows = buildTopicEvolutionWindows([
      point(0, 10, [1, 0]),
      point(100, 30, [0, 1]),
      point(101, 0, [1, 0]),
    ], 2);

    expect(windows).toHaveLength(1);
    expect(windows[0].weights).toEqual([0.25, 0.75]);
    expect(windows[0].paragraphCount).toBe(2);
    expect(windows[0].tokenTotal).toBe(40);
    expect(windows[0].end).toBe(101);
  });

  it("keeps empty character intervals distinct from zero-weight topics", () => {
    const points = [...Array.from({ length: 23 }, () => point(0, 10, [1, 0])), point(1000, 10, [0, 1])];
    const windows = buildTopicEvolutionWindows(points, 2);

    expect(windows).toHaveLength(3);
    expect(windows[1].weights).toBeNull();
    expect(windows[2].weights).toEqual([0, 1]);
  });
});
