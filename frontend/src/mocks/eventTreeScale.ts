import type { EventTreeListResponse } from "../api/narrativeTypes";

interface ScaleOptions {
  chapters: number;
  eventsPerChapter: number;
  arcs: number;
  outcomes: number;
}

/** 结构化规模夹具：只用于布局与性能检查，不代表真实长篇业务验收 */
export function buildScaleBook({ chapters, eventsPerChapter, arcs, outcomes }: ScaleOptions): EventTreeListResponse {
  const chapterList = Array.from({ length: chapters }, (_, index) => ({ chapter_id: index + 1, title: `第 ${index + 1} 章`, chapter_order: index + 1 }));
  const events: EventTreeListResponse["events"] = [];
  let position = 0;
  for (let chapter = 1; chapter <= chapters; chapter++) {
    for (let index = 0; index < eventsPerChapter; index++) {
      position += 100;
      events.push({
        event_id: `ev-${chapter}-${index}`, from: chapter, to: chapter,
        title: `第 ${chapter} 章事件 ${index}`,
        summary: `概要 ${chapter}-${index}`,
        event_type: "推进",
        status: "进行中",
        first_text_position: position,
        chapter_id: chapter,
        chapter_order: chapter,
      });
    }
  }
  const arcList = Array.from({ length: arcs }, (_, index) => ({ arc_id: `arc-${index}`, parent_arc_id: null, kind: index === 0 ? "main" : "subplot", title: `叙事线 ${index}`, objective: `叙事线 ${index} 的目标说明` }));
  const outcomeList = Array.from({ length: outcomes }, (_, index) => ({ outcome_id: `oc-${index}`, title: `结果 ${index}`, description: `结果 ${index} 的说明文字`, first_text_position: (index + 1) * 500 }));
  const eventArcLinks = events.flatMap((event, index) => [{ event_id: event.event_id, arc_id: `arc-${index % Math.max(1, arcs)}`, role: "推进", reason: "依据" }]);
  const eventOutcomeLinks = events.flatMap((event, index) => [{ event_id: event.event_id, outcome_id: `oc-${index % Math.max(1, outcomes)}`, reason: "依据" }]);
  return {
    run_id: "run-scale",
    chapters: chapterList,
    counts: {
      top_level_events: events.length, child_events: 0, all_events: events.length,
      outcomes: outcomeList.length, event_outcome_links: eventOutcomeLinks.length,
      arcs: arcList.length, event_arc_links: eventArcLinks.length, relations: 0, foreshadowing_actions: 0,
    },
    arcs: arcList,
    events,
    outcomes: outcomeList,
    event_arc_links: eventArcLinks,
    event_outcome_links: eventOutcomeLinks,
    relations: [],
    foreshadowing_actions: [],
    next_cursor: null,
  };
}

