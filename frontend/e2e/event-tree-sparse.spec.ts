import { test, expect } from "@playwright/test";
import sparseBook from "./fixtures/event-tree-sparse-book.json" with { type: "json" };

for (const viewport of [{ width: 1874, height: 875 }, { width: 1280, height: 720 }]) {
  test(`实数据快照的稀疏关联与完整文案边界 ${viewport.width}x${viewport.height}`, async ({ page }, testInfo) => {
    await page.setViewportSize(viewport);
    const errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.route("**/api/**", async route => {
      if (route.request().method() !== "GET") return route.abort();
      const path = new URL(route.request().url()).pathname;
      if (!path.startsWith("/api/")) return route.continue();
      let data: unknown = {};
      const novel = { novel_id: "229d1b8f", title: "重明传", filename: "重明传.txt", status: "completed", file_size: 1500, upload_time: "2026-10-19T00:00:00" };
      const task = { task_id: sparseBook.run_id, novel_id: "229d1b8f", status: "completed", progress: 100, created_at: "2026-10-19T00:00:00" };
      if (path.endsWith("/event-trees")) data = sparseBook;
      else if (path.endsWith("/tasks")) data = { novel_id: "229d1b8f", tasks: [task] };
      else if (path.endsWith("/status")) data = task;
      else if (path.endsWith("/229d1b8f")) data = novel;
      else if (/\/novels\/?$/.test(path)) data = { items: [novel], total: 1, page: 1, page_size: 12, total_pages: 1 };
      return route.fulfill({ json: data });
    });
    await page.goto(`/novels/229d1b8f/event-trees?task_id=${sparseBook.run_id}`);
    const canvas = page.getByLabel("事件树画布");
    await expect(canvas.locator("[data-arc-anchor]")).toHaveCount(8);
    await expect(page.getByText("156 个大事件", { exact: false })).toBeVisible();
    await expect.poll(() => canvas.evaluate(element => {
      for (let parent: HTMLElement | null = element as HTMLElement; parent; parent = parent.parentElement) if (Number(getComputedStyle(parent).opacity) < 1) return false;
      return true;
    })).toBe(true);
    const measurements = await canvas.evaluate(element => {
      const frame = element.getBoundingClientRect();
      const collect = (selector: string) => [...element.querySelectorAll<HTMLElement>(selector)].map(node => {
        const box = node.getBoundingClientRect();
        return { left: box.left, right: box.right, top: box.top, bottom: box.bottom, width: box.width, text: node.innerText };
      });
      return { frame: { top: frame.top, bottom: frame.bottom }, anchors: collect("[data-arc-anchor]"), outcomes: collect("[data-outcome-id]"), clamped: [...element.querySelectorAll("[data-outcome-id] p")].some(node => getComputedStyle(node).textOverflow === "ellipsis" || Number(getComputedStyle(node).webkitLineClamp) > 0) };
    });
    expect(measurements.clamped).toBe(false);
    for (const row of [measurements.anchors, measurements.outcomes]) {
      const sorted = row.toSorted((a, b) => a.left - b.left);
      for (const box of sorted) {
        expect(box.top).toBeGreaterThanOrEqual(measurements.frame.top);
        expect(box.bottom).toBeLessThanOrEqual(measurements.frame.bottom - 8);
      }
      for (let index = 1; index < sorted.length; index++) {
        const gap = sorted[index].left - sorted[index - 1].right;
        expect(gap).toBeGreaterThanOrEqual(16);
        expect(gap).toBeLessThanOrEqual(32);
      }
    }
    const seen = new Set<string>();
    const linked = new Set([...sparseBook.event_arc_links, ...sparseBook.event_outcome_links].map(link => link.event_id));
    const neutral = new Set<string>();
    const frame = (await canvas.boundingBox())!;
    const contentWidth = await canvas.locator(":scope > div").evaluate(element => (element as HTMLElement).offsetWidth);
    for (let offset = 0; offset < contentWidth; offset += frame.width * 0.6) {
      for (const id of await canvas.locator("[data-event-marker]").evaluateAll(nodes => nodes.map(node => node.getAttribute("data-event-marker")!))) {
        seen.add(id);
        if (!linked.has(id)) neutral.add(id);
      }
      await page.mouse.move(frame.x + frame.width * 0.8, frame.y + frame.height - 5);
      await page.mouse.down();
      await page.mouse.move(frame.x + frame.width * 0.2, frame.y + frame.height - 5);
      await page.mouse.up();
      await expect.poll(() => canvas.locator(":scope > div").evaluate(element => Number((element as HTMLElement).style.transform.match(/translateX\((-?[\d.]+)px\)/)?.[1] ?? 0))).toBeCloseTo(Math.max(frame.width - contentWidth, -offset - frame.width * 0.6), 0);
    }
    expect(seen.size).toBe(156);
    expect(neutral.size).toBe(94);
    await page.getByRole("button", { name: "复位画布" }).click();
    await expect.poll(() => canvas.evaluate(element => {
      for (let parent: HTMLElement | null = element as HTMLElement; parent; parent = parent.parentElement) if (Number(getComputedStyle(parent).opacity) < 1) return false;
      return true;
    })).toBe(true);
    await page.screenshot({ path: testInfo.outputPath("sparse-book-light.png"), animations: "disabled" });
    await page.getByRole("button", { name: "切换深浅模式" }).click();
    await expect(page.locator("html")).toHaveClass(/dark/);
    await page.screenshot({ path: testInfo.outputPath("sparse-book-dark.png"), animations: "disabled" });
    expect(errors).toEqual([]);
  });
}
