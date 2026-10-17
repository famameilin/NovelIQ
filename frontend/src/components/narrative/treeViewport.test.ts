import { expect, it } from "vitest";
import { clampX, locateX } from "./treeViewport";

it("画布比视口宽时平移钳制在完整内容边界内", () => {
  expect(clampX(50, 1000, 3000)).toBe(0);
  expect(clampX(-500, 1000, 3000)).toBe(-500);
  expect(clampX(-5000, 1000, 3000)).toBe(-2000);
});

it("画布比视口窄时整体居中，不保留多余横向位移", () => {
  expect(clampX(0, 1000, 600)).toBe(200);
  expect(clampX(-300, 1000, 600)).toBe(200);
});

it("定位只计算横向平移，目标中心落在视口中心且不越过边界", () => {
  expect(locateX(1000, 3000, 1500)).toBe(-1000);
  expect(locateX(1000, 3000, 100)).toBe(0);
  expect(locateX(1000, 3000, 2950)).toBe(-2000);
  expect(locateX(1000, 600, 300)).toBe(200);
});
