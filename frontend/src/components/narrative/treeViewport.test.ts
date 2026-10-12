import { expect, it } from "vitest";
import { fitTree, fitTreeBounds, treeCenter, zoomTree, type TreeFrame, type TreeViewport } from "./treeViewport";

const screenPoint = (view: TreeViewport, frame: TreeFrame, point: { x: number; y: number }) => {
  const center = treeCenter(frame, view.scale);
  return { x: center.x + view.x + point.x * view.scale, y: center.y + view.y + point.y * view.scale };
};

it("深处节点放大缩小时保住当前阅读点", () => {
  const frame = { width: 900, height: 650, canvasWidth: 2800, canvasHeight: 10231 };
  const view = { scale: .5, x: -200, y: 325 - 8610 * .5 };
  const target = { x: 1800, y: 8610 };
  const before = screenPoint(view, frame, target);
  expect(before).toEqual({ x: 450, y: 325 });
  const next = zoomTree(view, frame, .6);
  expect(screenPoint(next, frame, target)).toEqual(before);
  expect(screenPoint(zoomTree(next, frame, .4), frame, target)).toEqual(before);
});

it("选中点偏离视口中心时按该点缩放", () => {
  const frame = { width: 900, height: 650, canvasWidth: 1400, canvasHeight: 800 };
  const view = { scale: .5, x: 10, y: -20 };
  const target = { x: 1050, y: 600 };
  const anchor = screenPoint(view, frame, target);
  const after = screenPoint(zoomTree(view, frame, .9, anchor), frame, target);
  expect(after.x).toBeCloseTo(anchor.x);
  expect(after.y).toBeCloseTo(anchor.y);
});

it("适应全图同时容纳横向和纵向结构并居中", () => {
  for (const dimensions of [{ canvasWidth: 2600, canvasHeight: 10231 }, { canvasWidth: 4200, canvasHeight: 800 }]) {
    const frame = { width: 900, height: 650, ...dimensions };
    const view = fitTree(frame);
    const a = screenPoint(view, frame, { x: 0, y: 0 }), b = screenPoint(view, frame, { x: frame.canvasWidth, y: frame.canvasHeight });
    expect(a.x).toBeGreaterThanOrEqual(19.99);
    expect(a.y).toBeGreaterThanOrEqual(19.99);
    expect(b.x).toBeLessThanOrEqual(frame.width - 19.99);
    expect(b.y).toBeLessThanOrEqual(frame.height - 19.99);
    expect((a.x + b.x) / 2).toBeCloseTo(frame.width / 2);
    expect((a.y + b.y) / 2).toBeCloseTo(frame.height / 2);
  }
});

it("全书中心取景包含叙事线和外部说明，不受已展开全书的巨大边界影响", () => {
  const bounds = { left: 2200, top: 3400, width: 840, height: 625 };
  for (const screen of [{ width: 984, height: 498 }, { width: 1144, height: 678 }]) {
    const frame = { ...screen, canvasWidth: 6500, canvasHeight: 7100 };
    const view = fitTreeBounds(frame, bounds);
    const a = screenPoint(view, frame, { x: bounds.left, y: bounds.top });
    const b = screenPoint(view, frame, { x: bounds.left + bounds.width, y: bounds.top + bounds.height });
    expect(a.x).toBeGreaterThanOrEqual(15.99);
    expect(a.y).toBeGreaterThanOrEqual(15.99);
    expect(b.x).toBeLessThanOrEqual(frame.width - 15.99);
    expect(b.y).toBeLessThanOrEqual(frame.height - 15.99);
    expect(view.scale).toBeGreaterThan(.74);
    expect(view.scale).toBeLessThanOrEqual(1);
    expect((a.y + b.y) / 2).toBeCloseTo(frame.height / 2);
  }
});
