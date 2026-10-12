export interface TreeViewport { scale: number; x: number; y: number }
export interface TreeFrame { width: number; height: number; canvasWidth: number; canvasHeight: number }

export function treeCenter(frame: TreeFrame, scale: number) {
  return { x: (frame.width - frame.canvasWidth * scale) / 2, y: Math.max(0, (frame.height - frame.canvasHeight * scale) / 2) };
}

/** 以当前视口的同一阅读点缩放，深处节点不会随缩放倍率飞出画布 */
export function zoomTree(view: TreeViewport, frame: TreeFrame, nextScale: number, anchor = { x: frame.width / 2, y: frame.height / 2 }): TreeViewport {
  const before = treeCenter(frame, view.scale), after = treeCenter(frame, nextScale);
  const worldX = (anchor.x - before.x - view.x) / view.scale;
  const worldY = (anchor.y - before.y - view.y) / view.scale;
  return { scale: nextScale, x: anchor.x - worldX * nextScale - after.x, y: anchor.y - worldY * nextScale - after.y };
}

/** 适应已展开结构的两个方向，完整边界包含标题与节点 */
export function fitTree(frame: TreeFrame): TreeViewport {
  const scale = Math.min(1, Math.max(1, frame.width - 40) / frame.canvasWidth, Math.max(1, frame.height - 40) / frame.canvasHeight);
  const center = treeCenter(frame, scale);
  return { scale, x: (frame.width - frame.canvasWidth * scale) / 2 - center.x, y: (frame.height - frame.canvasHeight * scale) / 2 - center.y };
}

/** 全书中心按中心圆与直属叙事线的完整边界取景，保留已展开的外围分支 */
export function fitTreeBounds(frame: TreeFrame, bounds: { left: number; top: number; width: number; height: number }, padding = 16): TreeViewport {
  const scale = Math.min(1, Math.max(1, frame.width - padding * 2) / Math.max(1, bounds.width), Math.max(1, frame.height - padding * 2) / Math.max(1, bounds.height));
  const center = treeCenter(frame, scale);
  return { scale, x: frame.width / 2 - (bounds.left + bounds.width / 2) * scale - center.x, y: frame.height / 2 - (bounds.top + bounds.height / 2) * scale - center.y };
}
