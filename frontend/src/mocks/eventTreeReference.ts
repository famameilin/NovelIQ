import { eventQueueFixture, type FixtureInput } from "./eventQueueFixture";
import { indexEventQueues } from "../api/eventQueues";
import type { EventTreeEvent, EventTreeListResponse } from "../api/narrativeTypes";
import { scaleEventTreeResponse } from "./eventTreeScale";

export const EVENT_TREE_REFERENCE_NOVEL = "event-tree-reference";
export const EVENT_TREE_REFERENCE_TASK = "reference-scene";
export const EVENT_TREE_REFERENCE_SELECTED = "growth";

const rootCaptions = [
  ["成长线", "少年的成长与担当"], ["贺家线", "家族兴衰与使命"],
  ["朝堂线", "权力博弈与天下格局"], ["军旅线", "征战四方与家国守护"],
  ["江湖线", "江湖恩怨与侠义情义"], ["情感线", "爱恨纠葛与命运抉择"],
  ["宗门线", "修行求道与精神传承"],
];
const outcomeCaptions = [
  ["初遇与结识", "命运的相遇，\n一切故事的开始"], ["家族变故", "家族风云骤起，\n命运转向"],
  ["贺重明成长", "从少年到担当，\n走向真正的强大"], ["权臣博弈", "朝堂暗流涌动，\n各方势力角逐"],
  ["新政推行", "变革与理想，\n步履维艰"], ["大战蛮族", "烽火连天，\n守护山河"],
  ["修行突破", "在生死之间，\n踏上更高的境界"], ["生死相托", "至深的情感，\n最艰难的抉择"],
  ["天下归一", "众人之力，\n迎来新的天下"],
];

// 各分支记录真实归属、事件种类与共享引用，不存储画布坐标
const branches: Array<[number, string]> = [
  [0, "p0 t0 t0"],
  [0, "p7 p7"],
  [0, "d7 t7 p7 p0 p0 t0 p0"],
  [0, "t7 p7 p7 t7"],
  [0, "t7 d7"],
  [1, "p7"],
  [1, "t0 p1 t1 t1 p1 p1"],
  [1, "p1 p7 p7 p7"],
  [2, "t7 t7 d7 t7 t2"],
  [1, "p1 d1 p1 p1"],
  [0, "t7 p7 p7 p7 p7 p0 p0 p0 p2 p2"],
  [2, "p7 p7 p7"],
  [0, "g0"],
  [5, "p1 p5 p5 p5"],
  [2, "d7 t7 d7 d7"],
  [2, "p0 t0 t0"],
  [3, "p7 p7 p7 p7 d7"],
  [3, "t5 t5 t5 t5 t5 p7 p5 p5 p5 p5 p5"],
  [3, "p7 d7 p7 p5 p5 d7 d7"],
  [4, "p7 p7 p7 p7"],
  [4, "p7 p7"],
  [4, "t1 t1 t1 p1 d1 p1 p1 p1"],
  [4, "t7 p7 p7 p2 p2"],
  [4, "p1 p1 p1"],
  [5, "t5 p5 p5 t5"],
  [4, "p7 d7 p7 d7"],
  [5, "t5 p5 p5 t5 t5"],
  [5, "t1 p1 t1 t1 p1"],
  [5, "d7 d7 p7 p7 p7"],
  [5, "t5 t5"],
  [6, "t7 p7 p2 t2 p2"],
  [6, "p2 p7 d7"],
  [6, "t2 p2 p2 t2"],
  [6, "t7 p2 t2 t2"],
];

function buildReferenceBook(): EventTreeListResponse {
  const chapters = branches.map((_, index) => ({ chapter_id: index + 1, chapter_order: index + 1, title: `第 ${index + 1} 章` }));
  const roots: EventTreeEvent[] = rootCaptions.map(([title, problem], index) => ({
    event_id: `reference-root-${index}`, is_event_line: true, title, problem, summary: problem, event_type: "聚合", status: "已结束",
    from: 1, to: chapters.length, first_text_position: index, chapter_id: 1, chapter_order: 1,
  }));
  const book: FixtureInput = {
    run_id: EVENT_TREE_REFERENCE_TASK, chapters, events: [...roots],  edges: [], relations: [],
    outcomes: outcomeCaptions.map(([title, description], index) => ({ outcome_id: `reference-outcome-${index}`, title, description, first_text_position: index * 100 })),
     foreshadowing_actions: [], 
  };
  const eventTypes: Record<string, string> = { p: "推进", t: "转折", d: "细节", g: "成长转变" };
  branches.forEach(([fallbackOwner, kinds], branchIndex) => {
    const tokens = kinds.split(" ");
    const owners = tokens.map(token => Number(token[1]) === 7 ? fallbackOwner : Number(token[1]));
    const shared = tokens.map(token => Number(token[1]) === 7);
    const members = tokens.map((token, index): EventTreeEvent => ({
      is_event_line: false, event_id: token[0] === "g" ? EVENT_TREE_REFERENCE_SELECTED : `reference-event-${branchIndex}-${index}`,
      title: token[0] === "g" ? "贺重明成长" : `${outcomeCaptions[Math.min(8, Math.floor(branchIndex * 9 / branches.length))][0]}${index + 1}`,
      problem: "", summary: token[0] === "g" ? "历经家族变故与多方磨难，贺重明逐渐从懵懂的少年成长为能够独当一面的强者，开始承担家族与天下的责任。" : "各方人物在变故中作出选择，推动故事发展。",
      event_type: eventTypes[token[0]], status: "已结束", from: branchIndex + 1, to: branchIndex + 1,
      first_text_position: (branchIndex + 1) * 1000 + index * 10, chapter_id: branchIndex + 1, chapter_order: branchIndex + 1,
    }));
    book.events.push(...members);
    members.forEach((event, index) => {
      const sameBranch = members[index + 1] && owners[index + 1] === owners[index] && shared[index + 1] === shared[index];
      book.edges.push({
        parent: sameBranch ? members[index + 1].event_id : roots[owners[index]].event_id,
        child: event.event_id, reason: "子事件构成该段完整事件的发展过程", evidence: [{ chapter_id: branchIndex + 1 }],
      });
      if (shared[index] && !sameBranch) book.edges.push({
        parent: roots[(owners[index] + 2) % roots.length].event_id, child: event.event_id,
        reason: "多个父级共同引用完整子队列", evidence: [{ chapter_id: branchIndex + 1 }],
      });
    });
  });
  const related = ["家族变故", "拜师学艺", "第一次出征", "肩负家族重任"];
  related.forEach((title, index) => {
    const event = book.events.find(item => item.event_id === `reference-event-${[0, 6, 10, 14][index]}-0`)!;
    event.title = title;
    book.edges.find(edge => edge.child === event.event_id)!.parent = EVENT_TREE_REFERENCE_SELECTED;
  });
  // 每棵树的首层事件使用独立标题，画布关键节点不出现重复编号
  const branchTitles: Record<number, string[]> = {
    0: ["初遇与结识", "贺家遭变", "贺重明成长", "势力博弈", "天下归一", "少年立志", "初露锋芒", "家族使命", "锋芒初现", "家族托付", "初涉权局", "远行历练"],
    1: ["贺家遭变", "家族重整", "善后风波", "贺家军崛起", "家门荣辱", "族中暗流", "旧怨新仇", "家业交接", "族宴风波", "旧部来投", "庄园重整", "门庭再立"],
    2: ["初入朝堂", "权谋交锋", "各方博弈", "新政推行", "朝堂清洗", "御前陈奏", "朋党之争", "法度更张", "边报入朝", "朝议定策", "权柄交接", "新政受阻", "军报入朝", "朝局再变", "权臣伏诛", "朝野震动"],
    3: ["边境初战", "军报密信", "与灰灵石", "北荒决战", "铁骑出征", "军械整备", "雪原对峙", "班师回朝", "边关告急", "夜袭敌营", "军功受赏", "解甲归田"],
    4: ["初入江湖", "结识挚友", "江湖风波", "退隐山林", "市井奇遇", "渡口追踪", "客栈相逢", "旧友重逢", "镖局受托", "山道遇伏", "故人相托", "归隐田园"],
    5: ["沈遥情愫", "误会分离", "生死相护", "再多重逢", "旧信牵念", "月下相候", "远行告别", "并肩同行", "灯下守候", "旧约难违", "千里传书", "重逢有期"],
    6: ["拜入太学", "秘境试炼", "宗门纷争", "太学南北之争", "同窗结义", "经义辩难", "禁地探幽", "师门传承", "山门试炼", "同门切磋", "长老传道", "秘境寻踪"],
  };
  const converted = eventQueueFixture(book);
  const index = indexEventQueues(converted);
  const byId = new Map(converted.events.map(event => [event.event_id, event]));
  const rootIndexById = new Map(converted.queues.map(tree => [tree.tree_id, roots.findIndex(root => root.event_id === tree.event_ids[0])]));
  const preserved = new Set(["家族变故", "拜师学艺", "第一次出征", "肩负家族重任"]);
  const lineEntries = new Set(converted.event_line_ids.flatMap(id => {
    const first = index.trees.get(id)!.event_ids[0];
    return first ? [first] : [];
  }));
  for (const root of converted.event_line_ids) {
    const queue = index.trees.get(root)!;
    const heads = index.children.get(root)!.map(id => index.trees.get(id)!.event_ids[0]);
    const direct = [queue.event_ids[1], ...heads].filter((id): id is string => !!id);
    const events = direct.map(id => byId.get(id)!).filter(event => !lineEntries.has(event.event_id))
      .sort((a, b) => a.chapter_order - b.chapter_order || a.first_text_position - b.first_text_position || a.event_id.localeCompare(b.event_id));
    const titles = branchTitles[rootIndexById.get(root) ?? 0] ?? [];
    events.forEach((event, position) => {
      if (preserved.has(event.title)) return;
      event.title = titles[position] ?? `第 ${event.chapter_order} 章转折${position + 1}`;
    });
  }
  return converted;
}

export const referenceBook = buildReferenceBook();

/** 视觉夹具复用正式列表、详情和原文响应形状 */
export function eventTreeReferenceResponse(path: string, params: URLSearchParams, runId: string) {
  const response = scaleEventTreeResponse(referenceBook, path, params, runId);
  if (path.endsWith(`/nodes/${EVENT_TREE_REFERENCE_SELECTED}`)) {
    return { ...response, data: { ...(response.data as Record<string, unknown>), characters: ["贺重明", "猴子", "柱子"].map(name => ({ name })) } };
  }
  return response;
}
