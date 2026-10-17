/** 事件树画布固定阅读尺度，只允许横向平移；视口状态只有 x，没有缩放和纵向位移 */
export interface TreeViewportX { x: number }

/** 画布比视口窄时整体居中，否则平移范围钳制在完整内容边界内 */
export function clampX(x: number, frameWidth: number, canvasWidth: number): number {
  if (canvasWidth <= frameWidth) return (frameWidth - canvasWidth) / 2;
  return Math.min(0, Math.max(frameWidth - canvasWidth, x));
}

/** 定位操作只改变横向平移，让目标内容的横向中心落在视口中心 */
export function locateX(frameWidth: number, canvasWidth: number, contentX: number): number {
  return clampX(frameWidth / 2 - contentX, frameWidth, canvasWidth);
}
