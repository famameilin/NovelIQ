import {act, renderHook, waitFor} from "@testing-library/react";
import {QueryClient, QueryClientProvider} from "@tanstack/react-query";
import type {PropsWithChildren} from "react";
import {beforeEach, expect, it, vi} from "vitest";
import {useAnalysisStatus} from "./useAnalysisStatus";
import {useStreamStore} from "@/store/streamStore";
import {emptyAnalysisProjection} from "@/store/analysisProjection";
const api=vi.hoisted(()=>({get:vi.fn(),event:null as null | ((type:string,data:unknown,seq?:number)=>void),url:null as string|null}));
vi.mock("@/api/analysis",()=>({getTaskStatus:api.get}));
vi.mock("./useEventSource",()=>({useSSEListener:(url:string|null,options:{onEvent:(type:string,data:unknown,seq?:number)=>void})=>{api.url=url;api.event=options.onEvent;return {isConnected:false};}}));
function wrapper({children}:PropsWithChildren) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
let client:QueryClient;
beforeEach(()=>{client=new QueryClient({defaultOptions:{queries:{retry:false}}});api.get.mockReset();api.event=null;api.url=null;useStreamStore.getState().reset();});
it("HTTP 状态核对不扩充进度，运行任务通过 SSE 读取快照",async()=>{
 api.get.mockResolvedValue({novel_id:"novel",task_id:"task",status:"running"});
 const view=renderHook(()=>useAnalysisStatus("novel","task"),{wrapper});
 await waitFor(()=>expect(useStreamStore.getState().status).toBe("running"));
 expect(api.url).toContain("/tasks/task");expect(useStreamStore.getState()).not.toHaveProperty("progress");view.unmount();
});
it("终态仍读取快照，最终通知同步后才开放结果",async()=>{
 api.get.mockResolvedValue({status:"running"});const completed=vi.fn();
 const view=renderHook(()=>useAnalysisStatus("novel","task",{onCompleted:completed}),{wrapper});
 await waitFor(()=>expect(view.result.current.status).toBe("running"));
 act(()=>api.event?.("snapshot",{...emptyAnalysisProjection(),task_id:"task",status:"running",sync_pending:true}));
 act(()=>api.event?.("task_complete",{status:"completed",task_id:"task"},1));
 expect(completed).toHaveBeenCalledOnce();expect(view.result.current.projectionSynced).toBe(false);expect(api.url).not.toBeNull();
 act(()=>api.event?.("notification_status",{task_id:"task",warning:null,sync_pending:false}));
 expect(view.result.current.projectionSynced).toBe(true);view.unmount();
});
it("首次打开已失败任务和停止收尾均保持订阅",async()=>{
 api.get.mockResolvedValue({status:"failed"});
 const view=renderHook(()=>useAnalysisStatus("novel","task"),{wrapper});
 await waitFor(()=>expect(view.result.current.status).toBe("failed"));expect(api.url).toContain("/tasks/task");
 act(()=>api.event?.("snapshot",{...emptyAnalysisProjection(),task_id:"task",status:"cancelling"}));
 expect(api.url).not.toBeNull();view.unmount();
});
it("HTTP 先返回完成时继续等快照和通知尾部，不能提前切到结果",async()=>{
 api.get.mockResolvedValue({status:"completed"});
 const view=renderHook(()=>useAnalysisStatus("novel","task"),{wrapper});
 await waitFor(()=>expect(view.result.current.status).toBe("completed"));
 expect(view.result.current.projectionSynced).toBe(false);expect(api.url).not.toBeNull();
 act(()=>api.event?.("snapshot",{...emptyAnalysisProjection(),task_id:"task",status:"completed",sync_pending:true}));
 expect(view.result.current.projectionSynced).toBe(false);expect(api.url).not.toBeNull();
 act(()=>api.event?.("notification_status",{task_id:"task",warning:null,sync_pending:false}));
 expect(view.result.current.projectionSynced).toBe(true);expect(api.url).toBeNull();view.unmount();
});
it("新打开的无效任务读取失败后停止 SSE 重试",async()=>{
 api.get.mockRejectedValue(new Error('任务不存在'));
 const view=renderHook(()=>useAnalysisStatus('novel','missing'),{wrapper});
 await waitFor(()=>expect(view.result.current.query.isError).toBe(true));
 expect(api.url).toBeNull();view.unmount();
});
