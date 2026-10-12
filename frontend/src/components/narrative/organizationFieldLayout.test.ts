import { expect, it } from "vitest";
import type { NarrativeTreeNode } from "@/api/narrativeTypes";
import { arc, root, tree } from "@/mocks/narrativeData";
import { circleConnectionPath, circlePort, fieldDisplayOverlap, organizationBranchPaths, organizationFieldLayout, type FieldPosition } from "./organizationFieldLayout";

it("并列主线和独立支线围绕全书根，布局不改写归属", () => {
  const independent = { ...arc, node_id: "arc:independent", arc_id: "independent", title: "独立支线" };
  const parallel = { ...arc, node_id: "arc:parallel", arc_id: "parallel", title: "并列主线" };
  const nodes = [{ ...root, child_count: 3 }, arc, independent, parallel];
  const before = structuredClone(nodes);
  const arcs = [...tree.arcs, { ...tree.arcs[0], arc_id: "independent", kind: "subplot" as const }, { ...tree.arcs[0], arc_id: "parallel" }];
  const layout = organizationFieldLayout(nodes, arcs, 824);
  expect(layout.coreId).toBe("root");
  expect(layout.positions.get("root")?.core).toBe(true);
  expect([...layout.positions.keys()].sort()).toEqual(nodes.map(node => node.node_id).sort());
  expect(nodes).toEqual(before);
});

it("多层密集分支不丢节点，标签避让后仍在可平移画布内", () => {
  const groups: NarrativeTreeNode[] = Array.from({ length: 8 }, (_, index) => ({ node_id: `group:${index}`, parent_id: arc.node_id, kind: "group", title: `事件组 ${index}`, child_count: 12, arc_id: "a" }));
  const events: NarrativeTreeNode[] = groups.flatMap(group => Array.from({ length: 12 }, (_, index) => ({ node_id: `${group.node_id}:event:${index}`, parent_id: index === 11 ? `${group.node_id}:event:10` : group.node_id, kind: "event", title: `事件 ${index}`, child_count: index === 10 ? 1 : 0, chapter_order: index + 1 })));
  const nodes = [root, { ...arc, child_count: groups.length }, ...groups, ...events];
  const layout = organizationFieldLayout(nodes, tree.arcs, 824);
  expect(layout.coreId).toBe(root.node_id);
  expect(layout.positions.size).toBe(nodes.length);
  const boxes = [...layout.positions.values()];
  for (const [index, box] of boxes.entries()) {
    expect(box.left).toBeGreaterThanOrEqual(0);
    expect(box.top).toBeGreaterThanOrEqual(0);
    expect(box.left + box.width).toBeLessThanOrEqual(layout.width);
    expect(box.top + box.height).toBeLessThanOrEqual(layout.height);
    for (const part of [box.titleBox, box.metaBox, box.statusBox, box.descriptionBox]) {
      if (!part) continue;
      expect(part.left).toBeGreaterThanOrEqual(box.left);
      expect(part.top).toBeGreaterThanOrEqual(box.top);
      expect(part.left + part.width).toBeLessThanOrEqual(box.left + box.width + 1e-6);
      expect(part.top + part.height).toBeLessThanOrEqual(box.top + box.height + 1e-6);
    }
    expect(boxes.slice(index + 1).some(other => fieldDisplayOverlap(box, other, 15.99))).toBe(false);
  }
});

it("大量直属事件组分行向外排列，第一行不因数量增加被推到远处", () => {
  const groups: NarrativeTreeNode[] = Array.from({ length: 36 }, (_, index) => ({ node_id: `group:compact-${index}`, parent_id: arc.node_id, kind: "group", title: `第 ${index + 1} 章事件组`, child_count: 0, chapter_order: index + 1 }));
  const layout = organizationFieldLayout([root, { ...arc, child_count: groups.length }, ...groups], tree.arcs, 1100);
  const parent = layout.positions.get(arc.node_id)!;
  const distances = groups.map(node => { const child = layout.positions.get(node.node_id)!; return Math.hypot(child.x - parent.x, child.y - parent.y); });
  expect(Math.min(...distances)).toBeLessThan(400);
  expect(Math.max(...distances)).toBeLessThan(1800);
  expect(layout.positions.size).toBe(38);
});

it("圆外空白角可以交错排布，圆周和文字仍保持间距", () => {
  const point = (x: number, y: number): FieldPosition => ({ x, y, radius: 64, ringRadius: 72, core: false, tone: "main", labelSide: "right", left: x - 80, top: y - 80, width: 160, height: 160 });
  expect(fieldDisplayOverlap(point(0, 0), point(120, 120))).toBe(false);
  expect(fieldDisplayOverlap(point(0, 0), point(100, 100))).toBe(true);
  expect(fieldDisplayOverlap(point(0, 0), { ...point(120, 120), descriptionBox: { left: 0, top: 90, width: 100, height: 36 } })).toBe(false);
  expect(fieldDisplayOverlap(point(0, 0), { ...point(120, 120), descriptionBox: { left: 0, top: 80, width: 100, height: 36 } })).toBe(true);
});

it("唯一主线保留全书根，嵌套叙事线和事件子节点仍按类型定大小", () => {
  const nested: NarrativeTreeNode = { ...arc, node_id: "arc:nested", arc_id: "nested", parent_id: arc.node_id };
  const group: NarrativeTreeNode = { node_id: "group:1", parent_id: nested.node_id, kind: "group", title: "长标题".repeat(20), child_count: 1, chapter_order: 21 };
  const event: NarrativeTreeNode = { node_id: "event:1", parent_id: group.node_id, kind: "event", title: "原子事件".repeat(20), child_count: 1, is_foreshadowing_root: true, foreshadowing_status: "open" };
  const child: NarrativeTreeNode = { ...event, node_id: "event:2", parent_id: event.node_id, child_count: 0 };
  const layout = organizationFieldLayout([root, arc, nested, group, event, child], [...tree.arcs, { ...tree.arcs[0], arc_id: "nested", parent_arc_id: arc.arc_id! }], 900);
  expect(layout.coreId).toBe(root.node_id);
  expect(layout.positions.size).toBe(6);
  expect(layout.positions.get(root.node_id)?.radius).toBe(96);
  expect(layout.positions.get(arc.node_id)?.radius).toBe(64);
  expect(layout.positions.get(nested.node_id)?.radius).toBe(layout.positions.get(arc.node_id)?.radius);
  expect(layout.positions.get(group.node_id)?.radius).toBe(36);
  expect(layout.positions.get(child.node_id)?.radius).toBe(layout.positions.get(event.node_id)?.radius);
  expect(layout.positions.get(event.node_id)?.radius).toBe(6);
  expect(layout.positions.get(event.node_id)?.statusBox).toBeDefined();
});

it("待归属保留独立大圆，圆周端点不受外部标题和控件影响", () => {
  const unassigned: NarrativeTreeNode = { node_id: "unassigned", parent_id: root.node_id, kind: "unassigned", title: "待归属", child_count: 1 };
  const point: NarrativeTreeNode = { node_id: "event:point", parent_id: unassigned.node_id, kind: "event", title: "完整的外部事件标题".repeat(30), child_count: 0 };
  const layout = organizationFieldLayout([root, unassigned, point], [], 900);
  const a = layout.positions.get(unassigned.node_id)!;
  const b = layout.positions.get(point.node_id)!;
  expect(a.tone).toBe("neutral");
  expect(a.radius).toBe(64);
  for (const [node, toward, clearance] of [[a, b, 2], [b, a, 4]] as const) {
    const end = circlePort(node, toward, clearance);
    expect(Math.hypot(end.x - node.x, end.y - node.y)).toBeCloseTo(node.ringRadius + clearance);
  }
  expect(b.x).not.toBe(b.left + b.width / 2);
  expect(circlePort({ x: 20, y: 30, radius: 6 }, { x: 20, y: 30 })).toEqual({ x: 28, y: 30 });
});

it("事件因果线保持弧形并从无标题的一侧出入", () => {
  const group: NarrativeTreeNode = { node_id: "group:route", parent_id: arc.node_id, kind: "group", title: "事件组", child_count: 1 };
  const a: NarrativeTreeNode = { node_id: "event:route-a", parent_id: group.node_id, kind: "event", title: "放在点旁的长标题".repeat(10), child_count: 1 };
  const b: NarrativeTreeNode = { ...a, node_id: "event:route-b", parent_id: a.node_id, child_count: 0 };
  const layout = organizationFieldLayout([root, arc, group, a, b], tree.arcs, 900);
  const source = layout.positions.get(a.node_id)!, target = layout.positions.get(b.node_id)!;
  const route = circleConnectionPath(source, target);
  const side = source.labelSide === "right" ? -1 : 1;
  expect(route.startsWith(`M ${source.x + side * 8} ${source.y}`)).toBe(true);
  expect(route.endsWith(`${target.x + side * 10} ${target.y}`)).toBe(true);
  expect(route).toContain(" C ");
  expect(route).not.toMatch(/[LHVQ]/);
});

it("共享归属树干和支梢都是曲线，分支末端停在外圈之外", () => {
  const groups: NarrativeTreeNode[] = [1, 2, 3].map(index => ({ node_id: `group:curve-${index}`, parent_id: arc.node_id, kind: "group", title: `事件组 ${index}`, child_count: 0 }));
  const layout = organizationFieldLayout([root, arc, ...groups], tree.arcs, 900);
  const branch = organizationBranchPaths(layout.positions.get(arc.node_id)!, groups.map(node => ({ id: node.node_id, position: layout.positions.get(node.node_id)! })));
  expect(branch.trunk).toContain(" C ");
  expect(branch.trunk).not.toMatch(/[LHVQ]/);
  for (const group of groups) {
    const path = branch.paths.get(group.node_id)!;
    expect(path).toContain(" C ");
    expect(path).not.toMatch(/[LHVQ]/);
    const [x, y] = path.split(/[,\s]+/).slice(-2).map(Number);
    const point = layout.positions.get(group.node_id)!;
    expect(Math.hypot(x - point.x, y - point.y)).toBeCloseTo(point.ringRadius + 4);
  }
});

it("事件组到上方事件点的曲线不越过终点再折返形成小环", () => {
  const group: FieldPosition = { x: 3448, y: 1891, radius: 36, ringRadius: 36, core: false, tone: "teal", labelSide: "right", left: 3364, top: 1841, width: 168, height: 128 };
  const event: FieldPosition = { x: 3517, y: 1687, radius: 6, ringRadius: 6, core: false, tone: "teal", labelSide: "right", left: 3501, top: 1667, width: 178, height: 60, titleBox: { left: 3535, top: 1667, width: 144, height: 40 } };
  const values = circleConnectionPath(group, event).match(/-?\d*\.?\d+(?:e[+-]?\d+)?/g)!.map(Number);
  const [x, y, ax, ay, bx, by, ex, ey] = values;
  expect(values).toHaveLength(8);
  for (let sample = 0; sample <= 100; sample++) {
    const t = sample / 100, s = 1 - t;
    const px = s ** 3 * x + 3 * s ** 2 * t * ax + 3 * s * t ** 2 * bx + t ** 3 * ex;
    const py = s ** 3 * y + 3 * s ** 2 * t * ay + 3 * s * t ** 2 * by + t ** 3 * ey;
    expect(py).toBeGreaterThanOrEqual(event.y - 1e-6);
    expect(py).toBeLessThanOrEqual(y + 1e-6);
    expect(px > event.titleBox!.left && px < event.titleBox!.left + event.titleBox!.width && py > event.titleBox!.top && py < event.titleBox!.top + event.titleBox!.height).toBe(false);
  }
});

it("跨线曲线控制点的上拱也避开全书圆，不能只判断端点直线", () => {
  const point = (x: number, y: number, side: "left" | "right"): FieldPosition => ({ x, y, radius: 6, ringRadius: 6, core: false, tone: "teal", labelSide: side, left: side === "right" ? x - 16 : x - 162, top: y - 20, width: 178, height: 76, titleBox: { left: side === "right" ? x + 18 : x - 162, top: y - 20, width: 144, height: 40 } });
  const center: FieldPosition = { x: 0, y: 0, radius: 96, ringRadius: 112, core: true, tone: "main", labelSide: "right", left: -120, top: -120, width: 240, height: 240 };
  // 实测中的跨归属父子边：端点直线远离全书，旧的上方通道却穿过中心
  const path = circleConnectionPath(point(1315, 2573, "right"), point(-2471, -133, "left"), center);
  const tokens = path.match(/[MC]|-?\d*\.?\d+(?:e[+-]?\d+)?/g)!;
  let x = 0, y = 0;
  for (let index = 0; index < tokens.length;) {
    const command = tokens[index++];
    if (command === "M") { x = Number(tokens[index++]); y = Number(tokens[index++]); continue; }
    const [ax, ay, bx, by, ex, ey] = tokens.slice(index, index + 6).map(Number);
    index += 6;
    for (let sample = 0; sample <= 80; sample++) {
      const t = sample / 80, s = 1 - t;
      const px = s ** 3 * x + 3 * s ** 2 * t * ax + 3 * s * t ** 2 * bx + t ** 3 * ex;
      const py = s ** 3 * y + 3 * s ** 2 * t * ay + 3 * s * t ** 2 * by + t ** 3 * ey;
      expect(Math.hypot(px, py)).toBeGreaterThan(center.ringRadius + 2);
    }
    x = ex; y = ey;
  }
});

it("全书到叙事线的曲线绕开圆外目标说明", () => {
  const layout = organizationFieldLayout([root, arc], tree.arcs, 900);
  const source = layout.positions.get(root.node_id)!, target = layout.positions.get(arc.node_id)!;
  const box = target.descriptionBox!;
  const values = circleConnectionPath(source, target).match(/-?\d*\.?\d+(?:e[+-]?\d+)?/g)!.map(Number);
  const [x, y, ax, ay, bx, by, ex, ey] = values;
  for (let sample = 0; sample <= 100; sample++) {
    const t = sample / 100, s = 1 - t;
    const px = s ** 3 * x + 3 * s ** 2 * t * ax + 3 * s * t ** 2 * bx + t ** 3 * ex;
    const py = s ** 3 * y + 3 * s ** 2 * t * ay + 3 * s * t ** 2 * by + t ** 3 * ey;
    expect(px > box.left && px < box.left + box.width && py > box.top && py < box.top + box.height).toBe(false);
  }
});
