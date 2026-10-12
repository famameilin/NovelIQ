import type { NarrativeTreeNode, NarrativeTreeResponse } from "@/api/narrativeTypes";

export interface FieldBox { left: number; top: number; width: number; height: number }

export interface FieldPosition extends FieldBox {
  // 圆心用于连线与定位，完整边界用于避让与适应全图，两者不能混用
  x: number; y: number; radius: number; ringRadius: number; core: boolean;
  tone: "main" | "violet" | "teal" | "neutral";
  labelSide: "left" | "right";
  titleBox?: FieldBox;
  metaBox?: FieldBox;
  statusBox?: FieldBox;
  descriptionBox?: FieldBox;
}

const nodeRadii = { root: 96, arc: 64, unassigned: 64, group: 36, event: 6 };
const gap = 16;

/** 圆用实际圆周避让，文字用矩形避让，不能把圆外空白角当成可见内容 */
export function fieldDisplayOverlap(a: FieldPosition, b: FieldPosition, clearance = gap) {
  const parts = (node: FieldPosition) => [node.titleBox, node.metaBox, node.statusBox, node.descriptionBox].filter((box): box is FieldBox => !!box);
  const circleBoxOverlap = (circle: FieldPosition, box: FieldBox) => {
    const dx = Math.max(box.left - circle.x, circle.x - box.left - box.width, 0);
    const dy = Math.max(box.top - circle.y, circle.y - box.top - box.height, 0);
    return Math.hypot(dx, dy) < circle.ringRadius + clearance;
  };
  const boxesOverlap = (first: FieldBox, second: FieldBox) => first.left < second.left + second.width + clearance && first.left + first.width + clearance > second.left && first.top < second.top + second.height + clearance && first.top + first.height + clearance > second.top;
  return Math.hypot(a.x - b.x, a.y - b.y) < a.ringRadius + b.ringRadius + clearance
    || parts(a).some(box => circleBoxOverlap(b, box))
    || parts(b).some(box => circleBoxOverlap(a, box))
    || parts(a).some(first => parts(b).some(second => boxesOverlap(first, second)));
}

const captionBelow = (node: FieldPosition) => [node.descriptionBox, node.metaBox].some(box => box && box.top > node.y);

/** 返回圆周外的端点，标题宽度与透明点击范围不改变真实连线位置 */
export function circlePort(node: Pick<FieldPosition, "x" | "y" | "radius"> & { ringRadius?: number }, toward: { x: number; y: number }, clearance = 2) {
  const dx = toward.x - node.x, dy = toward.y - node.y;
  const distance = Math.hypot(dx, dy);
  const ux = distance ? dx / distance : 1, uy = distance ? dy / distance : 0;
  const radius = node.ringRadius ?? node.radius;
  return { x: node.x + ux * (radius + clearance), y: node.y + uy * (radius + clearance) };
}

/** 连线保持连续弧形，点旁的标题只朝外显示，曲线从另一侧出入 */
export function circleConnectionPath(a: FieldPosition, b: FieldPosition, core?: FieldPosition) {
  const path = connectionCurve(a, b);
  if (!core || a.core || b.core) return path;
  const firstAngle = Math.atan2(a.y - core.y, a.x - core.x), lastAngle = Math.atan2(b.y - core.y, b.x - core.x);
  const separateBranches = Math.abs(Math.atan2(Math.sin(lastAngle - firstAngle), Math.cos(lastAngle - firstAngle))) > .6;
  const distant = Math.min(Math.hypot(a.x - core.x, a.y - core.y), Math.hypot(b.x - core.x, b.y - core.y)) > 600;
  // 中心附近的直属短枝直接生长，外围路由只接管实际经过中心的远端关系
  return (separateBranches || distant) && curveCrossesCenter(path, core) ? curveAroundCore(a, b, core) : path;
}

function connectionCurve(a: FieldPosition, b: FieldPosition) {
  if (!a.titleBox && !b.titleBox) {
    const leaveBelow = captionBelow(a) && b.y > a.y;
    const arriveBelow = captionBelow(b) && a.y > b.y;
    if (leaveBelow || arriveBelow) {
      // 目标说明和章节在圆下方，曲线从文字旁绕入圆侧，不能穿过说明
      const node = leaveBelow ? a : b, other = leaveBelow ? b : a;
      const sign = other.x === node.x ? node.labelSide === "right" ? 1 : -1 : other.x > node.x ? 1 : -1;
      const column = sign > 0 ? node.left + node.width + 24 : node.left - 24;
      const start = circlePort(a, { x: column, y: leaveBelow ? a.y : b.y });
      const end = circlePort(b, { x: column, y: arriveBelow ? b.y : a.y }, 4);
      return `M ${start.x} ${start.y} C ${column} ${start.y}, ${column} ${end.y}, ${end.x} ${end.y}`;
    }
    const start = circlePort(a, b), end = circlePort(b, a, 4);
    const dx = end.x - start.x, dy = end.y - start.y;
    const horizontal = Math.abs(dx) >= Math.abs(dy);
    return horizontal
      ? `M ${start.x} ${start.y} C ${start.x + dx * .52} ${start.y}, ${end.x - dx * .52} ${end.y}, ${end.x} ${end.y}`
      : `M ${start.x} ${start.y} C ${start.x} ${start.y + dy * .52}, ${end.x} ${end.y - dy * .52}, ${end.x} ${end.y}`;
  }
  const sideA = a.labelSide === "right" ? -1 : 1, sideB = b.labelSide === "right" ? -1 : 1;
  const start = a.titleBox ? circlePort(a, { x: a.x + sideA, y: a.y }) : circlePort(a, b);
  const end = circlePort(b, b.titleBox ? { x: b.x + sideB, y: b.y } : a, 4);
  const bend = Math.min(72, Math.max(32, Math.abs(end.y - start.y) * .24));
  if (!a.titleBox && b.titleBox && Math.abs(a.y - b.y) > Math.max(a.height, b.height)) {
    // 圆到事件点沿生长方向接入，不越过点的高度再折返形成小环
    const belowCaption = captionBelow(a) && b.y > a.y;
    const entry = belowCaption ? circlePort(a, { x: a.x + sideB, y: a.y }) : start;
    const controlX = belowCaption ? sideB > 0 ? a.left + a.width + 24 : a.left - 24 : entry.x + (end.x - entry.x) * .42;
    const controlY = belowCaption ? entry.y : entry.y + (end.y - entry.y) * .42;
    return `M ${entry.x} ${entry.y} C ${controlX} ${controlY}, ${end.x + sideB * bend} ${end.y}, ${end.x} ${end.y}`;
  }
  if (a.titleBox && b.titleBox && a.labelSide === b.labelSide && Math.abs(a.y - b.y) > Math.max(a.height, b.height)) {
    return `M ${start.x} ${start.y} C ${start.x + sideA * bend} ${start.y}, ${end.x + sideB * bend} ${end.y}, ${end.x} ${end.y}`;
  }
  // 跨层连线绕过标题上方，用两段相切的贝塞尔弧，不能退化为直角折线
  const laneY = Math.min(a.top, b.top) - 36;
  const middle = { x: (start.x + end.x) / 2, y: laneY };
  const outward = unit(a, start);
  const first = a.titleBox ? { x: start.x + sideA * bend, y: start.y } : { x: start.x + outward.x * bend, y: start.y + outward.y * bend };
  return `M ${start.x} ${start.y} C ${first.x} ${first.y}, ${first.x} ${laneY}, ${middle.x} ${middle.y} C ${end.x + sideB * bend} ${laneY}, ${end.x + sideB * bend} ${end.y}, ${end.x} ${end.y}`;
}

type Point = { x: number; y: number };
const coordinate = (point: Point) => `${point.x} ${point.y}`;
function unit(from: Point, to: Point) {
  const length = Math.hypot(to.x - from.x, to.y - from.y) || 1;
  return { x: (to.x - from.x) / length, y: (to.y - from.y) / length };
}
function growthCurve(from: Point, to: Point, origin: Point) {
  const length = Math.hypot(to.x - from.x, to.y - from.y);
  const a = unit(origin, from), b = unit(origin, to);
  return `M ${coordinate(from)} C ${from.x + a.x * length * .42} ${from.y + a.y * length * .42}, ${to.x - b.x * length * .35} ${to.y - b.y * length * .35}, ${coordinate(to)}`;
}

/** 检查实际弧线而非端点直线，控制点上拱也可能使跨线关系进入中心 */
function curveCrossesCenter(path: string, core: Point) {
  const tokens = path.match(/[MC]|-?\d*\.?\d+(?:e[+-]?\d+)?/g)!;
  let x = 0, y = 0;
  for (let index = 0; index < tokens.length;) {
    const command = tokens[index++];
    if (command === "M") { x = Number(tokens[index++]); y = Number(tokens[index++]); continue; }
    const [ax, ay, bx, by, ex, ey] = tokens.slice(index, index + 6).map(Number);
    index += 6;
    for (let step = 0; step <= 32; step++) {
      const t = step / 32, s = 1 - t;
      const px = s ** 3 * x + 3 * s ** 2 * t * ax + 3 * s * t ** 2 * bx + t ** 3 * ex;
      const py = s ** 3 * y + 3 * s ** 2 * t * ay + 3 * s * t ** 2 * by + t ** 3 * ey;
      if (Math.hypot(px - core.x, py - core.y) < 540) return true;
    }
    x = ex; y = ey;
  }
  return false;
}

/** 跨线关系沿外围弧线绕过中心，全部展开时不能用远端连线贯穿全书和叙事线标题 */
function curveAroundCore(a: FieldPosition, b: FieldPosition, core: FieldPosition) {
  const firstAngle = Math.atan2(a.y - core.y, a.x - core.x), lastAngle = Math.atan2(b.y - core.y, b.x - core.x);
  const delta = Math.atan2(Math.sin(lastAngle - firstAngle), Math.cos(lastAngle - firstAngle));
  // 远端关系留在远端，不能把全书连线拉回中心周围形成巨大装饰圆
  const radius = Math.max(550, Math.min(Math.hypot(a.x - core.x, a.y - core.y), Math.hypot(b.x - core.x, b.y - core.y)) * .96);
  const polar = (angle: number) => ({ x: core.x + Math.cos(angle) * radius, y: core.y + Math.sin(angle) * radius });
  const start = circlePort(a, a.titleBox ? { x: a.x + (a.labelSide === "right" ? -1 : 1), y: a.y } : polar(firstAngle));
  const end = circlePort(b, b.titleBox ? { x: b.x + (b.labelSide === "right" ? -1 : 1), y: b.y } : polar(lastAngle), 4);
  const first = polar(firstAngle), firstLength = Math.hypot(first.x - start.x, first.y - start.y);
  const firstControl = a.titleBox ? { x: start.x + (a.labelSide === "right" ? -1 : 1) * Math.min(60, firstLength * .3), y: start.y } : { x: start.x + (first.x - start.x) * .4, y: start.y + (first.y - start.y) * .4 };
  // 进出外围圆弧的控制点沿切线放置，拼接处不能形成径向与圆弧的直角
  const turn = Math.sign(delta) || 1, approach = Math.min(radius * .3, firstLength * .3);
  let path = `M ${coordinate(start)} C ${coordinate(firstControl)}, ${first.x + Math.sin(firstAngle) * turn * approach} ${first.y - Math.cos(firstAngle) * turn * approach}, ${coordinate(first)}`;
  const segments = Math.max(1, Math.ceil(Math.abs(delta) / (Math.PI / 2))), step = delta / segments;
  for (let index = 0; index < segments; index++) {
    const fromAngle = firstAngle + index * step, toAngle = fromAngle + step;
    const from = polar(fromAngle), to = polar(toAngle), tangent = 4 / 3 * Math.tan(step / 4) * radius;
    path += ` C ${from.x - Math.sin(fromAngle) * tangent} ${from.y + Math.cos(fromAngle) * tangent}, ${to.x + Math.sin(toAngle) * tangent} ${to.y - Math.cos(toAngle) * tangent}, ${coordinate(to)}`;
  }
  const last = polar(lastAngle), distance = Math.hypot(end.x - last.x, end.y - last.y);
  const inward = unit(end, core);
  const second = b.titleBox ? { x: end.x + (b.labelSide === "right" ? -1 : 1) * Math.min(60, distance * .3), y: end.y } : { x: end.x + inward.x * distance * .3, y: end.y + inward.y * distance * .3 };
  const departure = Math.min(radius * .3, distance * .3);
  return `${path} C ${last.x - Math.sin(lastAngle) * turn * departure} ${last.y + Math.cos(lastAngle) * turn * departure}, ${coordinate(second)}, ${coordinate(end)}`;
}

/** 共享归属线逐级分叉，汇合点只用于走线，不增加节点或改变真实父子关系 */
export function organizationBranchPaths(parent: FieldPosition, children: { id: string; position: FieldPosition }[]) {
  const mean = (items: typeof children) => ({ x: items.reduce((sum, item) => sum + item.position.x, 0) / items.length, y: items.reduce((sum, item) => sum + item.position.y, 0) / items.length });
  const center = mean(children), outward = unit(parent, center);
  const join = { x: parent.x + outward.x * (parent.ringRadius + 36), y: parent.y + outward.y * (parent.ringRadius + 36) };
  const start = circlePort(parent, join);
  const trunks: string[] = [], paths = new Map<string, string>();
  if (captionBelow(parent) && outward.y > .25) {
    // 圆下方的章节和目标说明属于完整展示边界，树干从侧面绕出再向外分叉
    const sign = outward.x >= 0 ? 1 : -1;
    const side = circlePort(parent, { x: parent.x + sign, y: parent.y });
    const outerX = sign > 0 ? parent.left + parent.width + 24 : parent.left - 24;
    trunks.push(`M ${coordinate(side)} C ${outerX} ${side.y}, ${outerX} ${join.y}, ${coordinate(join)}`);
  } else trunks.push(growthCurve(start, join, parent));
  const ordered = [...children].sort((a, b) => (a.position.x - parent.x) * -outward.y + (a.position.y - parent.y) * outward.x - ((b.position.x - parent.x) * -outward.y + (b.position.y - parent.y) * outward.x));
  function fork(from: Point, items: typeof children, depth: number) {
    if (items.length === 1) {
      const child = items[0], node = child.position;
      const end = circlePort(node, node.titleBox ? { x: node.x + (node.labelSide === "right" ? -1 : 1), y: node.y } : from, 4);
      const direction = unit(parent, from), length = Math.hypot(end.x - from.x, end.y - from.y);
      const control = node.titleBox ? { x: end.x + (node.labelSide === "right" ? -1 : 1) * Math.min(60, length * .35), y: end.y } : { x: end.x - unit(parent, node).x * length * .35, y: end.y - unit(parent, node).y * length * .35 };
      paths.set(child.id, `M ${coordinate(from)} C ${from.x + direction.x * length * .45} ${from.y + direction.y * length * .45}, ${coordinate(control)}, ${coordinate(end)}`);
      return;
    }
    for (const part of [items.slice(0, Math.ceil(items.length / 2)), items.slice(Math.ceil(items.length / 2))]) {
      if (!part.length) continue;
      const target = mean(part), portion = Math.min(.72, .28 + depth * .12);
      // 分叉从上一个汇合点向目标前进，紧凑分支也不能折回父圆内部
      const point = { x: from.x + (target.x - from.x) * portion, y: from.y + (target.y - from.y) * portion };
      trunks.push(growthCurve(from, point, parent));
      fork(point, part, depth + 1);
    }
  }
  fork(join, ordered, 1);
  return { trunk: trunks.join(" "), paths };
}

function nodePosition(node: NarrativeTreeNode, x: number, y: number, tone: FieldPosition["tone"], labelSide: FieldPosition["labelSide"], description = false, angle = Math.PI / 2): FieldPosition {
  const radius = nodeRadii[node.kind];
  const ringRadius = radius + (node.kind === "root" ? 16 : node.kind === "arc" || node.kind === "unassigned" ? 8 : 0);
  const point: FieldPosition = { x, y, radius, ringRadius, core: node.kind === "root", tone, labelSide, left: x - ringRadius - 8, top: y - ringRadius - 8, width: ringRadius * 2 + 16, height: ringRadius * 2 + 16 };
  if (node.kind === "event") {
    const left = labelSide === "right" ? x + 18 : x - 162;
    point.titleBox = { left, top: y - 20, width: 144, height: 40 };
    point.metaBox = { left, top: y + 24, width: 144, height: 16 };
    if (node.is_foreshadowing_root) point.statusBox = { left, top: y + 42, width: 144, height: 16 };
    // 常用阅读倍率下预留点的点击区域，缩放后的最小屏幕尺寸由渲染层维持
    point.left = x - 16; point.top = y - 16; point.width = 32; point.height = 32;
  } else {
    if (node.kind === "group") point.metaBox = { left: x - 84, top: y + ringRadius + 10, width: 168, height: 32 };
    if (description) {
      // 说明朝中心之外放置，保留两行信息且不挤占全书圆与叙事线之间的连线
      point.descriptionBox = Math.sin(angle) < -.35
        ? { left: x - 90, top: y - ringRadius - 48, width: 180, height: 36 }
        : Math.sin(angle) > .65
          ? { left: labelSide === "right" ? x + ringRadius + 16 : x - ringRadius - 196, top: y - 12, width: 180, height: 36 }
          : { left: x - 90, top: y + ringRadius + 12, width: 180, height: 36 };
    }
  }
  const boxes = [point.titleBox, point.metaBox, point.statusBox, point.descriptionBox].filter((box): box is FieldBox => !!box);
  const right = Math.max(point.left + point.width, ...boxes.map(box => box.left + box.width));
  const bottom = Math.max(point.top + point.height, ...boxes.map(box => box.top + box.height));
  point.left = Math.min(point.left, ...boxes.map(box => box.left));
  point.top = Math.min(point.top, ...boxes.map(box => box.top));
  point.width = right - point.left; point.height = bottom - point.top;
  return point;
}

function translate(point: FieldPosition, dx: number, dy: number) {
  point.x += dx; point.y += dy; point.left += dx; point.top += dy;
  for (const box of [point.titleBox, point.metaBox, point.statusBox, point.descriptionBox]) {
    if (box) { box.left += dx; box.top += dy; }
  }
}

/** 只决定展示位置，大小表达节点类型，连线与归属仍服从已保存的真实关系 */
export function organizationFieldLayout(nodes: NarrativeTreeNode[], arcs: NarrativeTreeResponse["arcs"], availableWidth: number) {
  const width = Math.max(760, availableWidth);
  const root = nodes.find(node => node.node_id === "root");
  const positions = new Map<string, FieldPosition>();
  if (!root) return { width, height: 650, coreId: "root", positions };
  const arcOrder = new Map(arcs.map((arc, index) => [arc.arc_id, index]));
  const arcKinds = new Map(arcs.map(arc => [arc.arc_id, arc.kind]));
  const arcDescriptions = new Set(arcs.filter(arc => arc.objective).map(arc => arc.arc_id));
  const childrenById = new Map<string, NarrativeTreeNode[]>();
  for (const node of nodes) {
    if (!node.parent_id) continue;
    const siblings = childrenById.get(node.parent_id) ?? [];
    siblings.push(node); childrenById.set(node.parent_id, siblings);
  }
  for (const siblings of childrenById.values()) siblings.sort((a, b) => {
    if (a.kind === "arc" && b.kind === "arc") return (arcOrder.get(a.arc_id!) ?? 0) - (arcOrder.get(b.arc_id!) ?? 0);
    return (a.chapter_order ?? 0) - (b.chapter_order ?? 0) || a.node_id.localeCompare(b.node_id);
  });
  const children = (id: string) => childrenById.get(id) ?? [];
  const center = { x: width / 2, y: 304 };
  const occupied: FieldPosition[] = [];
  const overlaps = (point: FieldPosition) => occupied.some(other => fieldDisplayOverlap(point, other));
  function place(node: NarrativeTreeNode, x: number, y: number, tone: FieldPosition["tone"], side: FieldPosition["labelSide"], angle = Math.PI / 2) {
    const point = nodePosition(node, x, y, tone, side, arcDescriptions.has(node.arc_id!) && node.kind === "arc", angle);
    // 沿分支生长方向避让，不能把所有冲突节点推成同一列长直线
    const step = Math.max(48, Math.min(point.width, point.height) + gap);
    while (overlaps(point)) translate(point, Math.cos(angle) * step, Math.sin(angle) * step);
    positions.set(node.node_id, point); occupied.push(point);
    return point;
  }
  // 全书与唯一主线也保留各自身份，不能用主线大圆替代全书超大圆
  place(root, center.x, center.y, "main", "right");
  const branches = children(root.node_id);
  // 桌面中心使用横向椭圆，外部说明朝外，七条叙事线不用缩成小字才能看全
  const ringWidth = Math.max(290, branches.length * 46);
  const ringHeight = Math.max(216, branches.length * 32);
  const directions = new Map<string, number>();
  const sectors = new Map<string, number>();
  for (const [index, branch] of branches.entries()) {
    const angle = -Math.PI / 2 + 2 * Math.PI * index / Math.max(1, branches.length);
    const x = center.x + Math.cos(angle) * ringWidth, y = center.y + Math.sin(angle) * ringHeight;
    const side = x < center.x - 1 ? "left" : "right";
    const tone = branch.kind === "unassigned" ? "neutral" : arcKinds.get(branch.arc_id!) === "subplot" ? side === "right" ? "teal" : "violet" : "main";
    directions.set(branch.node_id, angle);
    sectors.set(branch.node_id, Math.min(Math.PI * .75, Math.PI * 2 / Math.max(1, branches.length) * .82));
    place(branch, x, y, tone, side, angle);
  }
  function placeChildren(parent: NarrativeTreeNode) {
    const a = positions.get(parent.node_id)!;
    const descendants = children(parent.node_id).filter(child => !positions.has(child.node_id));
    const direction = directions.get(parent.node_id) ?? 0;
    const sector = Math.max(parent.kind === "group" ? .65 : .28, sectors.get(parent.node_id) ?? .6);
    const templates = descendants.map(child => nodePosition(child, 0, 0, a.tone, a.labelSide, child.kind === "arc" && arcDescriptions.has(child.arc_id!), direction));
    const tangential = Math.max(0, ...templates.map(point => Math.abs(Math.sin(direction)) * point.width + Math.abs(Math.cos(direction)) * point.height));
    // 直属节点沿分支分行向外生长，数量只增加行数，不把第一行推到几千像素外
    let radius = Math.hypot(a.x - center.x, a.y - center.y) + a.ringRadius + 136;
    let row = 0, rowCount = 0;
    const rowStep = Math.max(144, ...templates.map(point => Math.abs(Math.cos(direction)) * point.width + Math.abs(Math.sin(direction)) * point.height + 64));
    for (const [index, child] of descendants.entries()) {
      if (row === rowCount) {
        if (index > 0) radius += rowStep;
        row = 0;
        rowCount = Math.min(descendants.length - index, Math.max(1, Math.floor(radius * sector / (tangential + 40))));
      }
      const count = rowCount;
      const spread = count < 2 ? 0 : Math.min(sector, (count - 1) * (tangential + 40) / radius);
      const angle = direction + (count > 1 ? (row / (count - 1) - .5) * spread : 0);
      const tone = child.kind === "unassigned" ? "neutral" : child.kind === "arc" && arcKinds.get(child.arc_id!) === "subplot" ? a.labelSide === "right" ? "teal" : "violet" : a.tone;
      let x = center.x + Math.cos(angle) * radius, y = center.y + Math.sin(angle) * radius;
      if (parent.kind === "event") {
        // 原子因果链在点旁延续，沿上下方向排布给弧线留下无文字的一侧
        const sign = a.y < center.y ? -1 : 1;
        x = a.x + (a.labelSide === "right" ? 1 : -1) * index * 190;
        y = a.y + sign * (Math.max(a.height, ...templates.map(point => point.height)) + 40);
      }
      const side = x < center.x - 1 ? "left" : "right";
      directions.set(child.node_id, angle);
      sectors.set(child.node_id, Math.max(.28, sector / count));
      place(child, x, y, tone, side, parent.kind === "event" ? a.y < center.y ? -Math.PI / 2 : Math.PI / 2 : angle);
      row++;
    }
    for (const child of descendants) placeChildren(child);
  }
  for (const branch of branches) placeChildren(branch);
  // 平移完整边界，标题、状态和叙事说明均纳入画布
  const minX = Math.min(0, ...occupied.map(point => point.left - 80));
  const minY = Math.min(0, ...occupied.map(point => point.top - 80));
  for (const point of occupied) translate(point, -minX, -minY);
  return {
    width: Math.max(width - minX, ...occupied.map(point => point.left + point.width + 80)),
    height: Math.max(650 - minY, ...occupied.map(point => point.top + point.height + 80)),
    coreId: root.node_id, positions,
  };
}
