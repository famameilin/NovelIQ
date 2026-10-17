export const EVENT_CARD_WIDTH = 280;
export const EVENT_CARD_MAX_HEIGHT = 420;
const CARD_GAP = 16;
const CASCADE_OFFSET = 28;

export interface CardPoint { x: number; y: number }

/** 子卡优先放在父卡右侧，空间不足时放左侧，再不足错位叠放，标题与关闭按钮保持可见 */
export function placeChildCard(parent: CardPoint, containerWidth: number, occupied: CardPoint[] = [], containerHeight = 650): CardPoint {
  const point = parent.x + EVENT_CARD_WIDTH + CARD_GAP + EVENT_CARD_WIDTH <= containerWidth
    ? { x: parent.x + EVENT_CARD_WIDTH + CARD_GAP, y: parent.y }
    : parent.x - CARD_GAP - EVENT_CARD_WIDTH >= 0
      ? { x: parent.x - CARD_GAP - EVENT_CARD_WIDTH, y: parent.y }
      : { x: Math.max(8, Math.min(parent.x + CASCADE_OFFSET, containerWidth - EVENT_CARD_WIDTH - 8)), y: parent.y + CASCADE_OFFSET };
  // 左右回绕可能落在祖先卡上，避让已有标题，正文区域允许叠放
  const headerHeight = 76;
  for (const other of [...occupied].sort((a, b) => a.y - b.y)) {
    if (point.x < other.x + EVENT_CARD_WIDTH && point.x + EVENT_CARD_WIDTH > other.x && point.y < other.y + headerHeight && point.y + headerHeight > other.y) point.y = other.y + headerHeight + 8;
  }
  return { ...point, y: Math.max(8, Math.min(point.y, containerHeight - headerHeight - 8)) };
}

/** 直接打开的卡（标记点击、目录、深链）按序号错位排布，避免互相完全覆盖 */
export function placeRootCard(index: number, containerWidth: number, anchor?: CardPoint, containerHeight = 650): CardPoint {
  if (anchor) {
    const right = anchor.x + 24;
    const x = right + EVENT_CARD_WIDTH <= containerWidth - 8 ? right : anchor.x - EVENT_CARD_WIDTH - 24;
    return { x: Math.max(8, Math.min(x, containerWidth - EVENT_CARD_WIDTH - 8)), y: Math.max(8, Math.min(anchor.y - 16, containerHeight - EVENT_CARD_MAX_HEIGHT - 8)) };
  }
  const right = Math.max(24, containerWidth - EVENT_CARD_WIDTH - 24);
  return { x: Math.min(24 + (index % 8) * CASCADE_OFFSET, right), y: 24 + (index % 6) * CASCADE_OFFSET };
}

