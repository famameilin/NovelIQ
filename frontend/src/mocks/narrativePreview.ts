import { eventTreeResponse } from "./narrativeData";
import type { PlotlineChange, PlotlineDimension, PlotlineTimelineResponse } from "../api/narrativeTypes";

export const NARRATIVE_PREVIEW_NOVEL = "narrative-design-demo";
export const NARRATIVE_PREVIEW_TASK = "narrative-design-task";

// 虚构样本，只在开发 mock 中提供，用于同内容视觉对照
const events = [
        {id:"e1",chapter:1,arc:"main",group:"追查失踪",title:"同伴突然失踪",summary:"同伴没有如约赴港，只留下一封未寄出的信。林舟开始调查。",quote:"桌上的茶已经冷了。那封信写到一半，许沉的名字落在被水洇开的末行。"},
        {id:"e2",chapter:2,arc:"identity",group:"玉佩线索",title:"找到刻纹玉佩",action:"埋设",summary:"旧屋里的一枚玉佩刻着独特纹章。它与失踪案的联系尚不明确。",quote:"玉面上刻着一只衔环的鸟，断开的尾羽正好指向窗外的灯塔。"},
        {id:"e3",chapter:3,arc:"main",group:"追查失踪",title:"仓库突发火灾",summary:"仓库突然起火。残留的货运标记把调查引向港口的秘密交易。",quote:"最后一根横梁倒下时，他看见烧焦的木箱上仍留着半枚货运印章。"},
        {id:"e4",chapter:4,arc:"ally",group:"旧友援手",title:"船夫暗中相助",summary:"阿岚帮林舟避开盘查，却不肯解释自己为何熟悉仓库的暗道。",quote:"阿岚把船撑进最窄的水道，低声说：先离开这里，其他的事天亮再说。"},
        {id:"e5",chapter:5,arc:"main",group:"锁定货船",title:"截获一封密信",summary:"一封密信记录了秘密出港计划，让调查有了明确的船名和时间。",quote:"信里没有署名，只有一行被反复描过的字：十二日夜，货船离港。"},
        {id:"e6",chapter:6,arc:"identity",group:"纹章线索",title:"纹章再次出现",action:"强化",summary:"海关档案中的纹章与玉佩一致。身份线索得到强化，玉佩的主人仍待查明。",quote:"林舟认出了那只衔环的鸟，连尾羽上的缺口，都与玉佩分毫不差。"},
        {id:"e7",chapter:7,arc:"ally",group:"信任裂痕",title:"旧友隐瞒行踪",summary:"目击证据与阿岚的说法矛盾，两人的信任开始动摇。",quote:"阿岚把手缩回袖中，说自己已经许多年不曾靠近那座仓库。"},
        {id:"e8",chapter:8,arc:"main",group:"锁定货船",title:"锁定出港货船",summary:"密信与货运记录相互印证。林舟找到运送失踪者的货船。",quote:"三本账册里，同一个船名总在失踪发生后离港。林舟终于圈住了它。"},
        {id:"e9",chapter:9,arc:"identity",group:"身份揭示",title:"族谱揭示身份",action:"疑似回收",summary:"族谱记载了玉佩的传承，指向幕后者的家族，回应此前的身份伏笔。",quote:"族谱上那个继承人的名字，正出现在货船的签押单上。"},
        {id:"e10",chapter:10,arc:"ally",group:"旧友抉择",title:"旧友交出证据",summary:"阿岚交出隐瞒的账本，为走私网络补上关键证据。",quote:"你要找的东西，一直在我这里。这一次，他没有避开林舟的目光。"},
        {id:"e11",chapter:11,arc:"main",group:"揭开真相",title:"灯塔正面对峙",summary:"身份线索与账本汇合。林舟在灯塔中质问幕后者，逼近真相。",quote:"林舟将玉佩与账本一并推到桌中央，问出了那个藏了许久的名字。"},
        {id:"e12",chapter:12,arc:"main",group:"揭开真相",title:"失踪真相揭开",summary:"关键证据得到印证，同伴失踪的原因被揭示，核心问题获得回应。",quote:"那封未寄出的信，终于有了一个完整的结尾。"}
      ];
const referenceChanges = [
        {id:"c1",chapter:1,channel:"investigation",type:"进展",title:"失踪调查启动",before:"去向不明",after:"开始追查失踪",sources:["e1"]},
        {id:"c2",chapter:2,channel:"foreshadow",type:"埋设",title:"玉佩伏笔埋设",before:"身份线索未知",after:"已埋设，含义待明",sources:["e2"]},
        {id:"c3",chapter:3,channel:"investigation",type:"转向",title:"调查方向改变",before:"追查失踪",after:"转查港口交易",sources:["e3"]},
        {id:"c4",chapter:4,channel:"relationship",type:"结盟",title:"获得外部助力",before:"独自调查",after:"阿岚成为援手",sources:["e4"]},
        {id:"c5",chapter:5,channel:"investigation",type:"进展",title:"行动目标明确",before:"追查港口交易",after:"追查秘密出港计划",sources:["e5"]},
        {id:"c6",chapter:6,channel:"foreshadow",type:"强化",title:"玉佩伏笔强化",before:"含义待明",after:"已强化，身份待查",sources:["e2","e6"]},
        {id:"c7",chapter:7,channel:"relationship",type:"裂痕",title:"同盟出现裂痕",before:"信任阿岚",after:"阿岚的说法受质疑",sources:["e7"]},
        {id:"c8",chapter:8,channel:"investigation",type:"进展",title:"调查目标锁定",before:"追查出港计划",after:"锁定目标货船",sources:["e5","e8"]},
        {id:"c9",chapter:9,channel:"foreshadow",type:"疑似回收",title:"玉佩伏笔疑似回收",before:"已强化，身份待查",after:"疑似回收，指向家族",sources:["e6","e9"]},
        {id:"c10a",chapter:10,channel:"relationship",type:"修复",title:"旧友重建信任",before:"隐瞒造成裂痕",after:"阿岚主动交出证据",sources:["e7","e10"]},
        {id:"c10b",chapter:10,channel:"investigation",type:"进展",title:"证据链补齐",before:"走私账本缺失",after:"走私网络得到印证",sources:["e8","e10"]},
        {id:"c11",chapter:11,channel:"investigation",type:"冲突",title:"调查转为对峙",before:"秘密追查",after:"公开质问幕后者",sources:["e11"]},
        {id:"c12",chapter:12,channel:"investigation",type:"回应",title:"核心疑问获回应",before:"失踪原因未明",after:"失踪真相揭示",sources:["e12"]}
      ];
const chapters = events.map(event => ({ chapter_id: event.chapter, order: event.chapter, title: event.title }));
const channelInfo: Record<string, { dimension: PlotlineDimension; subject: string }> = {
  investigation: { dimension: "plot", subject: "调查状态" },
  relationship: { dimension: "relationship", subject: "人物关系" },
  foreshadow: { dimension: "foreshadowing", subject: "玉佩伏笔" },
};
const changes: PlotlineChange[] = referenceChanges.map(change => ({
  plotline_change_id: change.id, chapter_id: change.chapter, chapter_order: change.chapter,
  dimension: channelInfo[change.channel].dimension, subject_id: change.channel, subject_title: channelInfo[change.channel].subject,
  title: change.title, before: change.before, after: change.after, deltas: [],
  action: ({ "埋设": "setup", "强化": "reinforce", "疑似回收": "payoff" } as Record<string, string>)[change.type] ?? null,
  source_event_ids: change.sources, source_fact_ids: [], evidence_scope: "paragraph", anchor_paragraph_ids: [change.chapter],
  evidence: change.sources.map(id => ({ chapter_id: events.find(event => event.id === id)!.chapter, paragraph_id: events.find(event => event.id === id)!.chapter })),
}));
/** 与正式接口同形的只读响应；样本状态来自 mock 任务，不触及业务任务 */
export function narrativePreviewResponse(path: string, params: URLSearchParams, runId = NARRATIVE_PREVIEW_TASK): { status: number; data: unknown } {
  if (path.includes("/event-trees")) return eventTreeResponse(path, params, runId);
  const cutoff = Math.min(12, Math.max(1, Number(params.get("through_chapter_id")) || 1));
  const id = decodeURIComponent(path.split("/").at(path.endsWith("/source") ? -2 : -1)!);
  const change = changes.find(item => item.plotline_change_id === id);
  if (path.includes("/timeline/changes/") && (!change || change.chapter_order > cutoff)) return { status: 404, data: { detail: { code: "CHANGE_NOT_VISIBLE" } } };
  if (path.endsWith("/source")) {
    const chapterId = Number(params.get("chapter_id")) || change?.chapter_id || 1;
    const event = events.find(item => item.chapter === chapterId);
    if (!event || (path.includes("/timeline/") && chapterId > cutoff)) return { status: 404, data: { detail: "SOURCE_NOT_VISIBLE" } };
    return { status: 200, data: { chapter_id: chapterId, title: event.title, paragraphs: [{ paragraph_id: chapterId, paragraph_index: 0, text: event.quote }] } };
  }
  if (path.includes("/timeline/changes/")) return { status: 200, data: change };
  if (path.endsWith("/timeline")) {
    const visible = changes.filter(item => item.chapter_order <= cutoff);
    const stateMap = new Map(visible.map(item => [item.subject_id, item]));
    const filtered = visible.filter(item => (!params.get("dimension") || item.dimension === params.get("dimension")) && (!params.get("subject_id") || item.subject_id === params.get("subject_id")) && (!params.get("q") || `${item.title}${item.subject_title}`.includes(params.get("q")!)));
    const windowed = filtered.filter(item => item.chapter_order >= (Number(params.get("window_start_chapter_id")) || 1));
    const offset = Number(params.get("cursor")) || 0, limit = Number(params.get("limit")) || 80;
    const distribution = [...new Map(filtered.map(item => [`${item.dimension}:${item.chapter_id}`, { chapter_id: item.chapter_id, chapter_order: item.chapter_order, dimension: item.dimension, count: filtered.filter(other => other.dimension === item.dimension && other.chapter_id === item.chapter_id).length }])).values()];
    const data: PlotlineTimelineResponse = {
      run_id: runId, chapters, through_chapter_id: cutoff, changes: windowed.slice(offset, offset + limit),
      states: [...stateMap.values()].map(item => ({ subject_id: item.subject_id, subject_title: item.subject_title, dimension: item.dimension, state: item.after, chapter_id: item.chapter_id, chapter_order: item.chapter_order })),
      subjects: [...stateMap.values()].map(item => ({ subject_id: item.subject_id, subject_title: item.subject_title, dimension: item.dimension })),
      total: windowed.length, next_cursor: offset + limit < windowed.length ? String(offset + limit) : null, distribution,
    };
    return { status: 200, data };
  }
  return { status: 404, data: { detail: "NOT_FOUND" } };
}
