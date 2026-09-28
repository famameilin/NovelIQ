import type { TopicSeriesPoint } from "@/api/types";

export interface TopicEvolutionWindow {
  start: number;
  end: number;
  paragraphCount: number;
  tokenTotal: number;
  weights: number[] | null;
}

/** 将原始段落权重按等长字符区间汇总，权重仍按实际入模词元数计算。 */
export function buildTopicEvolutionWindows(
  points: TopicSeriesPoint[],
  numTopics: number,
  maxWindows = 64,
): TopicEvolutionWindow[] {
  if (points.length === 0 || numTopics <= 0) return [];

  const lastPosition = Math.max(0, ...points.map((point) => point.start_position));
  const windowCount = Math.min(maxWindows, Math.max(1, Math.ceil(points.length / 8)), lastPosition + 1);
  const width = Math.max(1, Math.ceil((lastPosition + 1) / windowCount));
  const sums = Array.from({ length: windowCount }, () => Array<number>(numTopics).fill(0));
  const windows: TopicEvolutionWindow[] = Array.from({ length: windowCount }, (_, index) => ({
    start: index * width,
    end: Math.min(lastPosition, (index + 1) * width - 1),
    paragraphCount: 0,
    tokenTotal: 0,
    weights: null,
  }));

  points.forEach((point) => {
    if (point.token_count <= 0) return;
    const index = Math.min(windowCount - 1, Math.max(0, Math.floor(point.start_position / width)));
    const window = windows[index];
    window.paragraphCount += 1;
    window.tokenTotal += point.token_count;
    for (let topicId = 0; topicId < numTopics; topicId += 1) {
      sums[index][topicId] += (point.weights[topicId] ?? 0) * point.token_count;
    }
  });

  windows.forEach((window, index) => {
    if (window.tokenTotal > 0) window.weights = sums[index].map((sum) => sum / window.tokenTotal);
  });
  return windows;
}
