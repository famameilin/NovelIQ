import { expect, it } from "vitest";
import { clampAxis, clampViewport, locateViewport, zoomAround } from "./treeViewport";

it("画布比视口宽时平移钳制在完整内容边界内", () => {
  expect(clampAxis(50, 1000, 3000)).toBe(0);
  expect(clampAxis(-500, 1000, 3000)).toBe(-500);
  expect(clampAxis(-5000, 1000, 3000)).toBe(-2000);
});

it("画布比视口窄时整体居中，不保留多余位移", () => {
  expect(clampAxis(0, 1000, 600)).toBe(200);
  expect(clampAxis(-300, 1000, 600)).toBe(200);
});

it("横向和纵向分别钳制，缩放后的内容边界参与计算", () => {
  expect(clampViewport({ x: 50, y: 50 }, { width: 1000, height: 800 }, { width: 3000, height: 2000 })).toEqual({ x: 0, y: 0 });
  expect(clampViewport({ x: -3000, y: -3000 }, { width: 1000, height: 800 }, { width: 3000, height: 2000 })).toEqual({ x: -2000, y: -1200 });
  expect(clampViewport({ x: 0, y: 0 }, { width: 1000, height: 800 }, { width: 600, height: 400 })).toEqual({ x: 200, y: 200 });
});

it("定位让目标中心落在视口中心，缩放后仍不越过边界", () => {
  expect(locateViewport({ x: 1500, y: 1000 }, { width: 1000, height: 800 }, { width: 3000, height: 2000 }, 1)).toEqual({ x: -1000, y: -600 });
  expect(locateViewport({ x: 100, y: 100 }, { width: 1000, height: 800 }, { width: 3000, height: 2000 }, 1)).toEqual({ x: 0, y: 0 });
  expect(locateViewport({ x: 2950, y: 1900 }, { width: 1000, height: 800 }, { width: 3000, height: 2000 }, 1)).toEqual({ x: -2000, y: -1200 });
  expect(locateViewport({ x: 300, y: 200 }, { width: 1000, height: 800 }, { width: 600, height: 400 }, 1)).toEqual({ x: 200, y: 200 });
  expect(locateViewport({ x: 300, y: 200 }, { width: 1000, height: 800 }, { width: 600, height: 400 }, 2)).toEqual({ x: -100, y: 0 });
});

it("缩放围绕视口中心并保持当前阅读位置", () => {
  expect(zoomAround(0, 1000, 3000, 1, 2)).toBe(-500);
  expect(zoomAround(-1000, 1000, 3000, 1, 2)).toBe(-2500);
  expect(zoomAround(200, 1000, 600, 1, 0.5)).toBe(350);
});
