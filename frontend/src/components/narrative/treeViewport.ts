/** 事件线画布只维护平移与缩放，内容坐标使用布局尺度 */
export interface ViewportPoint { x: number; y: number }

/** 内容小于视口时居中，否则把位移钳制在完整内容边界内 */
export function clampAxis(value: number, frame: number, content: number): number {
  if (content <= frame) return (frame - content) / 2;
  return Math.min(0, Math.max(frame - content, value));
}

export function clampViewport(
  point: ViewportPoint, frame: { width: number; height: number }, content: { width: number; height: number },
): ViewportPoint {
  return { x: clampAxis(point.x, frame.width, content.width), y: clampAxis(point.y, frame.height, content.height) };
}

/** 定位让目标内容中心落在视口中心，并保留缩放后的边界 */
export function locateViewport(
  point: ViewportPoint, frame: { width: number; height: number }, content: { width: number; height: number }, zoom: number,
): ViewportPoint {
  return clampViewport(
    { x: frame.width / 2 - point.x * zoom, y: frame.height / 2 - point.y * zoom },
    frame,
    { width: content.width * zoom, height: content.height * zoom },
  );
}

/** 缩放围绕视口中心，保持当前阅读位置不跳 */
export function zoomAround(
  value: number, frameSize: number, contentSize: number, fromZoom: number, toZoom: number,
): number {
  const center = (frameSize / 2 - value) / fromZoom;
  return clampAxis(frameSize / 2 - center * toZoom, frameSize, contentSize * toZoom);
}
