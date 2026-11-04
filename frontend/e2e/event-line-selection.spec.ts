import { expect, test } from "@playwright/test";
import { selectedEventLineFixture } from "../src/mocks/eventQueueFixture";
import { scaleEventTreeResponse } from "../src/mocks/eventTreeScale";

test("非顶层事件线按节点标记展示，低覆盖响应正常打开", async ({ page }, testInfo) => {
  const book = selectedEventLineFixture();
  const novelId = "selected-lines-fixture";
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.setViewportSize({ width: 1756, height: 953 });
  await page.route("**/api/**", async route => {
    const address = new URL(route.request().url());
    const path = address.pathname;
    if (!path.startsWith("/api/")) return route.continue();
    const task = { task_id: book.run_id, novel_id: novelId, status: "completed", progress: 100, created_at: "2026-10-19T00:00:00" };
    const novel = { novel_id: novelId, title: "事件线选择验收", filename: "事件线选择验收.txt", status: "completed", file_size: 1500, upload_time: "2026-10-19T00:00:00" };
    let data: unknown = {};
    if (path.includes("/event-trees/nodes/")) {
      const response = scaleEventTreeResponse(book, path, address.searchParams);
      return route.fulfill({ status: response.status, json: response.data });
    }
    if (path.endsWith("/event-trees")) data = book;
    else if (path.endsWith("/tasks")) data = { novel_id: novelId, tasks: [task] };
    else if (path.endsWith("/status")) data = task;
    else if (path.endsWith(`/${novelId}`)) data = novel;
    else if (/\/novels\/?$/.test(path)) data = { items: [novel], total: 1, page: 1, page_size: 12, total_pages: 1 };
    return route.fulfill({ json: data });
  });
  await page.goto(`/novels/${novelId}/event-trees?task_id=${book.run_id}&event_id=s1`);
  const canvas = page.getByLabel("事件线画布");
  await expect(canvas.locator("[data-line-header]")).toHaveCount(5);
  await expect(page.getByLabel("事件数")).toContainText("20");
  const headers = await canvas.locator("[data-line-header]").allTextContents();
  expect(headers.some(title => title.includes("事件 a1"))).toBe(true);
  expect(headers.some(title => title.includes("事件 b1"))).toBe(true);
  expect(headers.some(title => title.includes("事件 a0"))).toBe(false);
  const detail = page.getByLabel("事件详情");
  await expect(detail).toContainText("事件 s1");
  await expect(detail).toContainText("事件 a1");
  await expect(page.getByText(/覆盖率|80%/)).toHaveCount(0);
  expect(errors).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("selected-inner-trees.png"), animations: "disabled" });
});
