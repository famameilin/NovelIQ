import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { AxiosResponse } from "axios";
import { afterEach, expect, it, vi } from "vitest";
import { apiClient } from "@/api/client";
import { chapters, changes, timeline } from "@/mocks/narrativeData";
import { ChapterChanges, ProgressionField } from "./ProgressionField";

afterEach(() => vi.restoreAllMocks());

it("密集章节按完整分布聚合，入口不受已加载记录数限制", async () => {
  const onGroup = vi.fn(), onSelect = vi.fn();
  render(<ProgressionField chapters={chapters} cutoffIndex={2} changes={[changes[0]]} distribution={[{ chapter_id: 2, chapter_order: 2, dimension: "plot", count: 83 }]} selectedId={null} onChapter={vi.fn()} onSelect={onSelect} onGroup={onGroup} />);
  await userEvent.click(within(screen.getByLabelText("变化清单")).getByRole("button", { name: /83/ }));
  expect(onGroup).toHaveBeenCalledWith({ chapterId: 2, chapterOrder: 2, dimension: "plot" });
  expect(onSelect).not.toHaveBeenCalled();
});

it("浏览章节窗口保持阅读截点，章节按钮仍使用全书索引", async () => {
  const book = Array.from({ length: 12 }, (_, index) => ({ chapter_id: index + 1, order: index + 1, title: `章节 ${index + 1}` }));
  const onChapter = vi.fn();
  render(<ProgressionField chapters={book} cutoffIndex={11} changes={[]} distribution={[]} selectedId={null} onChapter={onChapter} onSelect={vi.fn()} onGroup={vi.fn()} />);
  expect(screen.getByText(/当前显示第 9–12 章/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "向前浏览章节" }));
  expect(screen.getByText(/当前显示第 6–9 章/)).toBeInTheDocument();
  expect(onChapter).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "阅读至第 7 章" }));
  expect(onChapter).toHaveBeenCalledWith(6);
  await userEvent.click(screen.getByRole("button", { name: "定位阅读章节" }));
  expect(screen.getByRole("button", { name: "阅读至第 12 章" })).toHaveAttribute("aria-pressed", "true");
});

it("全书总览最多 20 章一屏，翻页浏览其余章节且不推进阅读截点", async () => {
  const book = Array.from({ length: 500 }, (_, index) => ({ chapter_id: index + 1, order: index + 1, title: `章节 ${index + 1}` }));
  const distribution = book.map(chapter => ({ chapter_id: chapter.chapter_id, chapter_order: chapter.order, dimension: "plot" as const, count: 1 }));
  const onChapter = vi.fn(), onGroup = vi.fn();
  const props = { chapters: book, cutoffIndex: 499, changes: [], distribution, selectedId: null, onChapter, onSelect: vi.fn(), onGroup };
  const { rerender } = render(<ProgressionField {...props} windowSize={0} />);
  expect(screen.getByText(/当前显示第 481–500 章/)).toBeInTheDocument();
  expect(within(screen.getByLabelText("变化清单")).getAllByRole("button")).toHaveLength(20);
  await userEvent.click(screen.getByRole("button", { name: "向前翻页章节" }));
  expect(screen.getByText(/当前显示第 462–481 章/)).toBeInTheDocument();
  expect(onChapter).not.toHaveBeenCalled();
  await userEvent.click(within(screen.getByLabelText("变化清单")).getByRole("button", { name: "462 / 情节推进 1 条变化" }));
  expect(onGroup).toHaveBeenCalledWith({ chapterId: 462, chapterOrder: 462, dimension: "plot" });
  rerender(<ProgressionField {...props} windowSize={4} />);
  expect(screen.getByText(/当前显示第 497–500 章/)).toBeInTheDocument();
});

it("章节聚合浮层独立读取全部分页，并保留主体与搜索条件", async () => {
  const records = Array.from({ length: 83 }, (_, index) => ({ ...changes[1], progression_change_id: `dense-${index}`, title: `密集变化 ${index + 1}` }));
  const api = vi.spyOn(apiClient, "get").mockImplementation(async (_url, config) => ({ data: { ...timeline(2), changes: config?.params?.cursor ? records.slice(80) : records.slice(0, 80), total: 83, next_cursor: config?.params?.cursor ? null : "chapter-next" } } as AxiosResponse));
  const onSelect = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  render(<QueryClientProvider client={client}><ChapterChanges novelId="novel-1" runId="run-a" group={{ chapterId: 2, chapterOrder: 2, dimension: "plot" }} subject="letter" q="线索" onClose={vi.fn()} onSelect={onSelect} /></QueryClientProvider>);
  await userEvent.click(await screen.findByRole("button", { name: "继续加载本章变化" }));
  await userEvent.click(await screen.findByRole("button", { name: /密集变化 83$/ }));
  expect(onSelect).toHaveBeenCalledWith("dense-82");
  expect(screen.queryByRole("button", { name: "继续加载本章变化" })).not.toBeInTheDocument();
  expect(api.mock.calls[1][1]?.params).toMatchObject({ through_chapter_id: 2, window_start_chapter_id: 2, dimension: "plot", subject_id: "letter", q: "线索", cursor: "chapter-next" });
});
