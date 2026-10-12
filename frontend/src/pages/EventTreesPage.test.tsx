import type { ReactNode } from "react";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { AxiosResponse } from "axios";
import { arc, eventA, eventB, installNarrativeApi, renderNarrative, root, tree, treeDetail } from "@/test/narrativeFixtures";
import type { NarrativeTreeDetail, NarrativeTreeNode } from "@/api/narrativeTypes";

vi.mock("@/components/layout/AnalysisWorkspace", () => ({ AnalysisWorkspace: ({ children }: { children: ReactNode }) => <main>{children}</main> }));
let api: ReturnType<typeof installNarrativeApi>;
beforeEach(() => {
  api = installNarrativeApi();
  // jsdom 不计算布局，显式提供桌面画布尺寸，初始化取景不能依赖零宽矩形
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
    return this.getAttribute("aria-label") === "事件树画布" ? new DOMRect(0, 0, 1000, 650) : new DOMRect();
  });
});
afterEach(() => { vi.restoreAllMocks(); window.getSelection()?.removeAllRanges(); });
const url = "/novels/novel-1/event-trees?task_id=task-a";

it("完整消费全书分页，根与所有叙事线可达", async () => {
  api.mockResolvedValueOnce({ data: { ...tree, nodes: [tree.nodes[1]], next_cursor: "skeleton-2" } } as AxiosResponse)
    .mockResolvedValueOnce({ data: { ...tree, nodes: [tree.nodes[0]] } } as AxiosResponse);
  renderNarrative(url);
  await screen.findByRole("region", { name: "全书事件树" });
  expect(api.mock.calls.some(([, config]) => config?.params?.cursor === "skeleton-2")).toBe(true);
  expect(api.mock.calls.filter(([path]) => String(path).endsWith("/event-trees")).every(([, config]) => config?.params?.expand_all === true)).toBe(true);
  expect(within(screen.getByLabelText("事件树画布")).getByRole("button", { name: "全书问题" })).toBeInTheDocument();
});

it("事件点与标题共用选择操作，圆不再提供折叠且小点保持最小点击尺寸", async () => {
  const base = api.getMockImplementation()!;
  const group: NarrativeTreeNode = { node_id: "group:circle", kind: "group", parent_id: arc.node_id, title: "事件组完整名称", child_count: 1, chapter_order: 2 };
  const point = { ...eventA, parent_id: group.node_id, child_count: 0 };
  api.mockImplementation(async (path, config) => {
    if (String(path).endsWith("/novels/novel-1")) return { data: { title: "验收小说" } } as AxiosResponse;
    if (config?.params?.expand_all) return { data: { ...tree, nodes: [root, arc, group, point], edges: [...tree.edges, { source_id: arc.node_id, target_id: group.node_id, kind: "organization" }, { source_id: group.node_id, target_id: point.node_id, kind: "organization" }] } } as AxiosResponse;
    if (String(path).endsWith(encodeURIComponent(point.node_id))) return { data: { ...treeDetail(point), path: [root, arc, group, point] } } as AxiosResponse;
    return base(path, config);
  });
  renderNarrative(url);
  const canvas = await screen.findByLabelText("事件树画布");
  expect(within(canvas).getByRole("button", { name: group.title })).toBeInTheDocument();
  expect(canvas.querySelector("button[aria-expanded]")).toBeNull();
  const select = await within(canvas).findByRole("button", { name: point.title });
  expect(canvas.querySelector("button button")).toBeNull();
  expect(canvas.querySelector('[data-node-kind="root"] [data-node-symbol]')).toBeVisible();
  expect(canvas.querySelector('[data-node-kind="root"] [data-node-ring]')).toBeVisible();
  expect(canvas.querySelector('[data-node-kind="root"] [data-node-title]')).toHaveClass("font-serif");
  await waitFor(() => expect(canvas.querySelector('[data-node-kind="root"] [data-node-title]')).toHaveTextContent("验收小说"));
  expect(canvas.querySelector('[data-node-kind="root"] [data-node-context]')).toHaveTextContent(root.title);
  expect(within(canvas).getByRole("button", { name: root.title })).toHaveAttribute("title", root.title);
  expect(canvas.querySelector('[data-node-kind="arc"] [data-node-description]')).toHaveTextContent("解开谜团");
  await userEvent.click(select.querySelector("[data-node-symbol]")!);
  expect(await screen.findByRole("dialog", { name: "节点详情" })).toHaveTextContent(point.title);
  expect(select.closest("article")).toHaveAttribute("data-selected", "true");
  await userEvent.click(screen.getByRole("button", { name: "缩小画布" }));
  const scale = JSON.parse(localStorage.getItem("novel-1:run-a:event-trees")!).scale;
  const hit = select.querySelector<HTMLElement>("[data-event-hit-target]")!;
  expect(parseFloat(hit.style.width) * scale).toBeGreaterThanOrEqual(28);
  expect(parseFloat(hit.style.height) * scale).toBeGreaterThanOrEqual(28);
});

it("默认展开含后页的全部事件，重新进入仍可见后页选中事件", async () => {
  localStorage.setItem("novel-1:run-a:event-trees", JSON.stringify({ collapsed: ["root", arc.node_id], expanded: ["root"] }));
  const first = renderNarrative(url);
  const canvas = await screen.findByLabelText("事件树画布");
  await userEvent.click(await within(canvas).findByRole("button", { name: "隐藏的末页事件" }));
  expect(await screen.findByRole("dialog", { name: "节点详情" })).toHaveTextContent("隐藏的末页事件");
  first.unmount();
  renderNarrative(url);
  await waitFor(() => expect(within(screen.getByLabelText("事件树画布")).getByRole("button", { name: "隐藏的末页事件" })).toBeInTheDocument());
  expect(JSON.parse(localStorage.getItem("novel-1:run-a:event-trees")!)).not.toHaveProperty("collapsed");
  expect(JSON.parse(localStorage.getItem("novel-1:run-a:event-trees")!)).not.toHaveProperty("expanded");
  expect(api.mock.calls.some(([, config]) => config?.params?.cursor === "all-second")).toBe(true);
});

it("全书搜索从概览定位具体事件，保持全部节点并打开本页详情", async () => {
  localStorage.setItem("novel-1:run-a:event-trees", JSON.stringify({ scale: .3 }));
  renderNarrative(url);
  await userEvent.type(await screen.findByRole("textbox", { name: "搜索全书事件" }), "隐藏");
  await userEvent.click(await within(screen.getByLabelText("全书结构目录")).findByRole("button", { name: "隐藏的末页事件" }));
  expect(await screen.findByRole("dialog", { name: "节点详情" })).toHaveTextContent("隐藏的末页事件");
  expect(screen.getByLabelText("事件树画布").querySelectorAll("article")).toHaveLength(4);
  expect(JSON.parse(localStorage.getItem("novel-1:run-a:event-trees")!).scale).toBeGreaterThanOrEqual(.85);
  expect(screen.queryByRole("button", { name: /时间轴/ })).not.toBeInTheDocument();
});

it("中心结构放得下时按实际尺寸阅读，选择与适配不再隐藏节点", async () => {
  renderNarrative(url);
  const canvas = await screen.findByLabelText("事件树画布");
  await waitFor(() => expect(JSON.parse(localStorage.getItem("novel-1:run-a:event-trees")!).scale).toBe(1));
  expect(canvas.querySelectorAll("article")).toHaveLength(4);
  expect(screen.queryByRole("button", { name: /收起分支|全部展开|^折叠 |^展开 / })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "放大画布" }));
  const scale = JSON.parse(localStorage.getItem("novel-1:run-a:event-trees")!).scale;
  await userEvent.click(within(canvas).getByRole("button", { name: eventA.title }));
  await screen.findByRole("dialog", { name: "节点详情" });
  expect(JSON.parse(localStorage.getItem("novel-1:run-a:event-trees")!).scale).toBe(scale);
  await userEvent.click(screen.getByRole("button", { name: "适应分支" }));
  expect(canvas.querySelectorAll("article")).toHaveLength(4);
  await userEvent.click(screen.getByRole("button", { name: "适应全图" }));
  expect(canvas.querySelectorAll("article")).toHaveLength(4);
  await userEvent.click(screen.getByRole("button", { name: "恢复100%倍率" }));
  expect(JSON.parse(localStorage.getItem("novel-1:run-a:event-trees")!).scale).toBe(1);
});

it("默认中心取景完整保留七条叙事线与说明，避免首屏裁切圆和文字", async () => {
  const base = api.getMockImplementation()!;
  const arcs = Array.from({ length: 7 }, (_, index) => ({ ...arc, node_id: `arc:center-${index}`, arc_id: `center-${index}`, title: `叙事线 ${index}`, child_count: 0 }));
  api.mockImplementation(async (path, config) => config?.params?.expand_all
    ? { data: { ...tree, nodes: [{ ...root, child_count: 7 }, ...arcs], arcs: arcs.map(node => ({ ...tree.arcs[0], arc_id: node.arc_id!, title: node.title })) } } as AxiosResponse
    : base(path, config));
  vi.mocked(HTMLElement.prototype.getBoundingClientRect).mockImplementation(function (this: HTMLElement) {
    return this.getAttribute("aria-label") === "事件树画布" ? new DOMRect(0, 0, 1000, 500) : new DOMRect();
  });
  const originalObserver = globalThis.ResizeObserver;
  vi.stubGlobal("ResizeObserver", class {
    private callback: ResizeObserverCallback;
    constructor(callback: ResizeObserverCallback) { this.callback = callback; }
    observe(element: Element) { this.callback([{ target: element, contentRect: new DOMRect(0, 0, 1000, 500) } as ResizeObserverEntry], this as ResizeObserver); }
    unobserve() {}
    disconnect() {}
  });
  const rendered = renderNarrative(url);
  try {
    const canvas = await screen.findByLabelText("事件树画布");
    await waitFor(() => expect(JSON.parse(localStorage.getItem("novel-1:run-a:event-trees")!)?.scale).toBeGreaterThan(0));
    const [x, y, scale] = (canvas.firstElementChild as HTMLElement).style.transform.match(/-?\d*\.?\d+(?:e[+-]?\d+)?/gi)!.map(Number);
    expect(scale).toBeLessThan(1);
    const nodes = [...canvas.querySelectorAll<HTMLElement>("article")];
    expect(nodes).toHaveLength(8);
    for (const node of nodes) {
      const left = x + parseFloat(node.style.left) * scale, top = y + parseFloat(node.style.top) * scale;
      expect(left).toBeGreaterThanOrEqual(15.99);
      expect(top).toBeGreaterThanOrEqual(15.99);
      expect(left + parseFloat(node.style.width) * scale).toBeLessThanOrEqual(984.01);
      expect(top + parseFloat(node.style.height) * scale).toBeLessThanOrEqual(484.01);
    }
  } finally {
    rendered.unmount();
    vi.stubGlobal("ResizeObserver", originalObserver);
  }
});

it("并列分支始终可见，搜索、详情与重新进入不筛掉其他分支", async () => {
  const base = api.getMockImplementation()!;
  const other = { ...arc, node_id: "arc:other", arc_id: "other", title: "另一条支线", child_count: 1 };
  const target = { ...eventB, parent_id: other.node_id, arc_id: other.arc_id };
  const book = { ...tree, nodes: [root, arc, other, eventA, target], edges: [...tree.edges, { source_id: root.node_id, target_id: other.node_id, kind: "organization" }, { source_id: arc.node_id, target_id: eventA.node_id, kind: "organization" }, { source_id: other.node_id, target_id: target.node_id, kind: "organization" }], arcs: [...tree.arcs, { ...tree.arcs[0], arc_id: other.arc_id, title: other.title, kind: "subplot" as const }] };
  api.mockImplementation(async (path, config) => {
    if (config?.params?.expand_all) return { data: book } as AxiosResponse;
    if (config?.params?.q) return { data: { ...book, total: 1, matches: [{ node_id: target.node_id, title: target.title, ancestor_ids: [root.node_id, other.node_id], chapter_id: 3, chapter_order: 3 }] } } as AxiosResponse;
    if (String(path).endsWith(encodeURIComponent(target.node_id))) return { data: { ...treeDetail(target), path: [root, other, target] } } as AxiosResponse;
    return base(path, config);
  });
  const first = renderNarrative(url);
  const canvas = await screen.findByLabelText("事件树画布");
  expect(within(canvas).getByRole("button", { name: eventA.title })).toBeInTheDocument();
  expect(within(canvas).getByRole("button", { name: eventB.title })).toBeInTheDocument();
  await userEvent.type(screen.getByRole("textbox", { name: "搜索全书事件" }), "隐藏");
  await userEvent.click(await within(screen.getByLabelText("全书结构目录")).findByRole("button", { name: target.title }));
  expect(await screen.findByRole("dialog", { name: "节点详情" })).toHaveTextContent(target.title);
  expect(canvas.querySelectorAll("article")).toHaveLength(5);
  expect(within(canvas).getByRole("button", { name: eventA.title })).toBeInTheDocument();
  first.unmount();
  renderNarrative(url);
  await screen.findByRole("dialog", { name: "节点详情" });
  expect(within(screen.getByLabelText("事件树画布")).getByRole("button", { name: eventA.title })).toBeInTheDocument();
  expect(within(screen.getByLabelText("事件树画布")).getByRole("button", { name: eventB.title })).toBeInTheDocument();
});

it("关系保留方向与类型，点击未加载目标补齐路径并选中，保留其他节点", async () => {
  const base = api.getMockImplementation()!;
  const group: NarrativeTreeNode = { node_id: "group:hidden", kind: "group", parent_id: arc.node_id, title: "隐藏事件组", child_count: 1, chapter_order: 3 };
  const target: NarrativeTreeNode = { ...eventB, node_id: "event:c", title: "未加载的关联目标", parent_id: group.node_id };
  const relation: NarrativeTreeDetail["relations"][number] = { source_id: eventB.node_id, target_id: target.node_id, kind: "causal", title: "因果关联", direction: "outgoing", related_node: target, ancestor_ids: [root.node_id, arc.node_id, group.node_id] };
  api.mockImplementation(async (path, config) => {
    if (String(path).endsWith(encodeURIComponent(target.node_id))) return { data: { ...treeDetail(target), path: [root, arc, group, target] } } as AxiosResponse;
    const result = await base(path, config) as AxiosResponse;
    if (String(path).includes("/nodes/") && String(path).endsWith(encodeURIComponent(eventB.node_id))) result.data = { ...result.data, relations: [relation, { ...relation, kind: "local_parent", title: "局部父子" }] };
    return result;
  });
  renderNarrative(url);
  await userEvent.type(await screen.findByRole("textbox", { name: "搜索全书事件" }), "隐藏");
  await userEvent.click(await within(screen.getByLabelText("全书结构目录")).findByRole("button", { name: eventB.title }));
  const relations = await screen.findByRole("region", { name: "真实关系" });
  expect(within(relations).getAllByRole("button")).toHaveLength(1);
  expect(relations).toHaveTextContent("指向 · 因果关联、局部父子");
  await userEvent.click(within(relations).getByRole("button", { name: /未加载的关联目标/ }));
  await waitFor(() => expect(within(screen.getByRole("dialog", { name: "节点详情" })).getByRole("heading", { name: target.title })).toBeInTheDocument());
  expect(within(screen.getByLabelText("事件树画布")).getByRole("button", { name: eventA.title })).toBeInTheDocument();
  expect(within(screen.getByLabelText("事件树画布")).getByRole("button", { name: target.title }).closest("article")).toHaveAttribute("data-selected", "true");
});

it("同向父子和因果只绘一条线，伏笔状态在画布与详情可读", async () => {
  const base = api.getMockImplementation()!;
  const flagged = { ...eventA, child_count: 1, is_foreshadowing_root: true, foreshadowing_status: "likely_paid_off" as const };
  api.mockImplementation(async (path, config) => {
    const result = await base(path, config) as AxiosResponse;
    if (config?.params?.expand_all) result.data = { ...tree, nodes: [root, arc, flagged, { ...eventB, parent_id: eventA.node_id }], edges: [...tree.edges, { source_id: arc.node_id, target_id: eventA.node_id, kind: "organization" }, { source_id: eventA.node_id, target_id: eventB.node_id, kind: "local_parent" }, { source_id: eventA.node_id, target_id: eventB.node_id, kind: "causal" }] };
    if (String(path).includes("/nodes/") && String(path).endsWith(encodeURIComponent(eventA.node_id))) result.data = treeDetail(flagged);
    return result;
  });
  renderNarrative(url);
  await screen.findByLabelText("事件树画布");
  const canvas = screen.getByLabelText("事件树画布");
  await userEvent.click(await within(canvas).findByRole("button", { name: eventA.title }));
  expect(canvas).toHaveTextContent("疑似回收");
  expect(await screen.findByRole("dialog", { name: "节点详情" })).toHaveTextContent("伏笔状态：疑似回收");
  await userEvent.click(within(canvas).getByRole("button", { name: eventB.title }));
  const paths = canvas.querySelectorAll('path[data-source-id="event:a"][data-target-id="event:b"]');
  expect(paths).toHaveLength(1);
  expect(paths[0]).toHaveAttribute("data-kinds", "local_parent causal");
  expect(paths[0]).toHaveAttribute("marker-end");
});

it("原文键盘焦点留在弹窗，Esc 仅关闭原文并恢复阅读按钮焦点", async () => {
  renderNarrative(url);
  await screen.findByLabelText("事件树画布");
  await userEvent.click(await within(screen.getByLabelText("事件树画布")).findByRole("button", { name: eventA.title }));
  const opener = await screen.findByRole("button", { name: "阅读原文" });
  await userEvent.click(opener);
  const reader = await screen.findByRole("dialog", { name: "章节原文" });
  await waitFor(() => expect(reader).toHaveTextContent("1 / 3"));
  for (let i = 0; i < 8; i++) { await userEvent.tab(); expect(reader.contains(document.activeElement)).toBe(true); }
  await userEvent.keyboard("{Escape}");
  expect(screen.queryByRole("dialog", { name: "章节原文" })).not.toBeInTheDocument();
  expect(screen.getByRole("dialog", { name: "节点详情" })).toHaveTextContent(eventA.title);
  await waitFor(() => expect(opener).toHaveFocus());
  await userEvent.keyboard("{Escape}");
  expect(screen.queryByRole("dialog", { name: "节点详情" })).not.toBeInTheDocument();
});

it("普通滚轮围绕鼠标位置缩放，连续输入累积且不会滚动页面", async () => {
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
    return this.getAttribute("aria-label") === "事件树画布" ? new DOMRect(120, 80, 1000, 650) : new DOMRect();
  });
  renderNarrative(url);
  const canvas = await screen.findByLabelText("事件树画布");
  await waitFor(() => expect(JSON.parse(localStorage.getItem("novel-1:run-a:event-trees")!).scale).toBe(1));
  const transform = () => (canvas.firstElementChild as HTMLElement).style.transform.match(/-?\d*\.?\d+(?:e[+-]?\d+)?/gi)!.map(Number);
  const before = transform();
  const world = { x: (250 - before[0]) / before[2], y: (150 - before[1]) / before[2] };
  const wheel = (deltaY: number, deltaMode = 0) => new WheelEvent("wheel", { bubbles: true, cancelable: true, clientX: 370, clientY: 230, deltaY, deltaMode });
  const first = wheel(-120);
  fireEvent(canvas, first);
  expect(first.defaultPrevented).toBe(true);
  await waitFor(() => expect(transform()[2]).toBeGreaterThan(1));
  let after = transform();
  expect(after[0] + world.x * after[2]).toBeCloseTo(250);
  expect(after[1] + world.y * after[2]).toBeCloseTo(150);
  fireEvent(canvas, wheel(120));
  await waitFor(() => expect(transform()[2]).toBeCloseTo(1));
  act(() => { fireEvent(canvas, wheel(-120)); fireEvent(canvas, wheel(-120)); });
  expect(transform()[2]).toBeCloseTo(Math.exp(.48));
  fireEvent(canvas, wheel(2, 1));
  after = transform();
  expect(after[2]).toBeCloseTo(Math.exp(.48 - .064));
  expect(after[0] + world.x * after[2]).toBeCloseTo(250);
  expect(after[1] + world.y * after[2]).toBeCloseTo(150);
  expect(canvas.querySelectorAll("article")).toHaveLength(4);
  const outside = wheel(120);
  fireEvent(screen.getByRole("main"), outside);
  expect(outside.defaultPrevented).toBe(false);
  expect(transform()).toEqual(after);
});

it("拖动画布只平移节点，阻止文字选择、原生拖放并在丢失捕获后停止", async () => {
  renderNarrative(url);
  const canvas = await screen.findByLabelText("事件树画布");
  Object.defineProperty(canvas, "setPointerCapture", { value: vi.fn() });
  await waitFor(() => expect(JSON.parse(localStorage.getItem("novel-1:run-a:event-trees")!)?.scale).toBeGreaterThan(0));
  const selection = window.getSelection()!;
  const range = document.createRange();
  range.selectNodeContents(canvas.querySelector("[data-node-title]")!);
  selection.addRange(range);
  expect(selection.toString()).not.toBe("");
  expect(canvas).toHaveClass("select-none");
  const before = JSON.parse(localStorage.getItem("novel-1:run-a:event-trees")!);
  const pointer = (type: string, x: number, y: number) => new MouseEvent(type, { bubbles: true, cancelable: true, clientX: x, clientY: y });
  const start = pointer("pointerdown", 200, 180);
  fireEvent(canvas.querySelector("article > small")!, start);
  expect(start.defaultPrevented).toBe(true);
  expect(selection.isCollapsed).toBe(true);
  fireEvent(canvas, pointer("pointermove", 330, 235));
  fireEvent(canvas, pointer("pointerup", 330, 235));
  const after = JSON.parse(localStorage.getItem("novel-1:run-a:event-trees")!);
  expect(after.x - before.x).toBe(130);
  expect(after.y - before.y).toBe(55);
  expect(after.scale).toBe(before.scale);
  expect(after.selected).toBe(before.selected);
  expect(canvas.querySelectorAll("article")).toHaveLength(4);
  const nativeDrag = new Event("dragstart", { bubbles: true, cancelable: true });
  fireEvent(canvas, nativeDrag);
  expect(nativeDrag.defaultPrevented).toBe(true);
  fireEvent(canvas, pointer("pointerdown", 330, 235));
  fireEvent(canvas, new Event("lostpointercapture", { bubbles: true }));
  fireEvent(canvas, pointer("pointermove", 400, 300));
  expect(JSON.parse(localStorage.getItem("novel-1:run-a:event-trees")!)).toEqual(after);
});

it("节点点击保留默认焦点行为，画布外的详情文字仍可选择复制", async () => {
  renderNarrative(url);
  const canvas = await screen.findByLabelText("事件树画布");
  const button = within(canvas).getByRole("button", { name: eventA.title });
  const press = new MouseEvent("pointerdown", { bubbles: true, cancelable: true, button: 0 });
  fireEvent(button.querySelector("[data-node-title]")!, press);
  expect(press.defaultPrevented).toBe(false);
  await userEvent.click(button);
  const detail = await screen.findByRole("dialog", { name: "节点详情" });
  const title = within(detail).getByRole("heading", { name: eventA.title });
  expect(title.closest(".select-none")).toBeNull();
  const range = document.createRange();
  range.selectNodeContents(title);
  window.getSelection()!.removeAllRanges();
  window.getSelection()!.addRange(range);
  expect(window.getSelection()!.toString()).toBe(eventA.title);
});

it("打开详情后等画布宽度测量完成再按节点圆心定位", async () => {
  const originalObserver = globalThis.ResizeObserver;
  let reportResize: (width: number) => void = () => {};
  vi.stubGlobal("ResizeObserver", class {
    private callback: ResizeObserverCallback;
    constructor(callback: ResizeObserverCallback) { this.callback = callback; }
    observe(element: Element) { reportResize = width => this.callback([{ target: element, contentRect: new DOMRect(0, 0, width, 650) } as ResizeObserverEntry], this as ResizeObserver); }
    unobserve() {}
    disconnect() {}
  });
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
    return this.getAttribute("aria-label") === "事件树画布" ? new DOMRect(0, 0, document.querySelector('[role="dialog"][aria-label="节点详情"]') ? 600 : 1000, 650) : new DOMRect();
  });
  const rendered = renderNarrative(url);
  try {
    const canvas = await screen.findByLabelText("事件树画布");
    await userEvent.click(within(canvas).getByRole("button", { name: eventA.title }));
    await screen.findByRole("dialog", { name: "节点详情" });
    // 先让详情列完成一轮绘制，再模拟随后到达的宽度通知
    await act(async () => { await new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))); });
    act(() => reportResize(600));
    await waitFor(() => {
      const point = canvas.querySelector('[data-selected="true"]')!;
      const transform = (canvas.firstElementChild as HTMLElement).style.transform.match(/-?\d*\.?\d+/g)!.map(Number);
      expect(transform[0] + Number(point.getAttribute("data-node-x")) * transform[2]).toBeCloseTo(300, 4);
      expect(transform[1] + Number(point.getAttribute("data-node-y")) * transform[2]).toBeCloseTo(325, 4);
    });
  } finally {
    rendered.unmount();
    vi.stubGlobal("ResizeObserver", originalObserver);
  }
});
