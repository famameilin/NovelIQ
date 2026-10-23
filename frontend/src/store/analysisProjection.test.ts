import {beforeEach,describe,expect,it} from "vitest";
import {emptyAnalysisProjection,mergeAnalysisNotice} from "./analysisProjection";
import {useStreamStore} from "./streamStore";

describe("分析通知归并",()=>{
  beforeEach(()=>useStreamStore.getState().reset());
  it("尝试失败后等待重选保持整项任务运行",()=>{
    let p: ReturnType<typeof emptyAnalysisProjection>={...emptyAnalysisProjection(),status:"running"};
    p=mergeAnalysisNotice(p,"agent_activity",{invocation_id:"first",activity:"error",message:"回合耗尽"},1);
    p=mergeAnalysisNotice(p,"agent_activity",{invocation_id:"first",activity:"retry"},2);
    expect(p.status).toBe("running");
    expect(p.error).toBeNull();
    expect(p.executions.first.activity).toBe("retry");
  });
  it("同一增量不重复拼接，快照替换前缀",()=>{
    useStreamStore.getState().setTaskId("a");
    const snapshot=mergeAnalysisNotice(emptyAnalysisProjection(),"llm_output",{invocation_id:"agent",content:"前缀"},10);
    useStreamStore.getState().applyNotice("a","snapshot",snapshot,10);
    for(let i=0;i<2;i++)useStreamStore.getState().applyNotice("a","llm_output",{invocation_id:"agent",content:"后缀"},11);
    expect(useStreamStore.getState().projection.executions.agent.output).toBe("前缀后缀");
  });
  it("A→B→A 后使用快照恢复，拒绝跨任务旧事件",()=>{
    const store=useStreamStore.getState();store.setTaskId("a");
    store.applyNotice("a","snapshot",{...emptyAnalysisProjection(),cursor:100},100);
    store.setTaskId("b");store.setTaskId("a");
    store.applyNotice("b","llm_output",{invocation_id:"wrong",content:"串扰"},101);
    expect(useStreamStore.getState().projection.executions.wrong).toBeUndefined();
    store.applyNotice("a","snapshot",{...emptyAnalysisProjection(),cursor:100,status:"running"},100);
    expect(useStreamStore.getState().snapshotReady).toBe(true);
    expect(useStreamStore.getState().projection.cursor).toBe(100);
  });
  it("离座和缓存淘汰后保留已选执行，同工位新住户不改变选择",()=>{
    const store=useStreamStore.getState();store.setTaskId("task");
    store.applyNotice("task","agent_activity",{invocation_id:"first",reservation_id:"r",activity:"starting"},1);
    store.selectExecution("first");
    for(let i=2;i<150;i++)store.applyNotice("task","agent_activity",{invocation_id:`agent-${i}`,reservation_id:`r-${i}`},i);
    expect(useStreamStore.getState().projection.executions.first).toBeUndefined();
    expect(useStreamStore.getState().pinnedExecution?.invocation_id).toBe("first");
    expect(useStreamStore.getState().selectedInvocation).toBe("first");
  });
  it("同名工具用真实调用身份匹配，保存状态独立于输出",()=>{
    let p=emptyAnalysisProjection();
    p=mergeAnalysisNotice(p,"tool_call",{invocation_id:"agent",tool_call_id:"c1",content:"execute_code",status:"started"},1);
    p=mergeAnalysisNotice(p,"tool_call",{invocation_id:"agent",tool_call_id:"c2",content:"execute_code",status:"success"},2);
    expect(p.executions.agent.tools.c1.status).toBe("started");
    expect(p.executions.agent.tools.c2.status).toBe("success");
    p=mergeAnalysisNotice(p,"llm_output",{invocation_id:"agent",content:"结束"},3);
    expect(p.executions.agent.activity).toBe("generating");
    p=mergeAnalysisNotice(p,"work_saved",{invocation_id:"agent"},4);
    expect(p.executions.agent.activity).toBe("saved");
  });
  it("重取同任务快照保留所选执行，切换任务则清除详情",()=>{
    const store=useStreamStore.getState();store.setTaskId('task');
    store.applyNotice('task','agent_activity',{invocation_id:'agent',activity:'saving'},1);
    store.selectExecution('agent');
    useStreamStore.setState({snapshotReady:true});
    store.resetStreamForTask('task');
    expect(useStreamStore.getState().snapshotReady).toBe(false);
    expect(useStreamStore.getState().selectedInvocation).toBe('agent');
    expect(useStreamStore.getState().pinnedExecution?.activity).toBe('saving');
    store.resetStreamForTask('other');
    expect(useStreamStore.getState().selectedInvocation).toBeNull();
    expect(useStreamStore.getState().projection.executions).toEqual({});
  });
});
