/** 分析过程中的角色、动作与计数名称 */
const roles: Record<string, string> = {
  entity: "实体与关系", event: "事件与参与者", metric: "对话与章级证据",
  annotation: "章节标注", case: "案例诊断", report: "报告收尾",
};
const activities: Record<string, string> = {
  starting: "启动中", thinking: "推理中", generating: "正在生成", tool: "工具执行",
  working: "处理中", saving: "保存中", saved: "保存已确认", retry: "等待重新选举", cancelled: "已取消", error: "异常",
};
const steps: Record<string, string> = {confirmed_chapters: "已保存章节", processing: "处理进度"};
export const executionRole = (value?: string) => roles[value ?? ""] ?? "Agent";
export const executionActivity = (value?: string) => activities[value ?? ""] ?? "状态未记录";
export const progressName = (value: string) => steps[value] ?? value;
export const executionSummary = (record: {sub_stage?: string; chapter_id?: number | null; activity?: string}) =>
  `${executionRole(record.sub_stage)}${record.chapter_id ? `·${record.chapter_id}章` : ""}·${executionActivity(record.activity)}`;
