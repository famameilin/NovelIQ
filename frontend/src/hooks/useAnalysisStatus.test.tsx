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
it("运行中的任务按状态接口定状态并连接进度流",async()=>{
 api.get.mockResolvedValue({novel_id:"novel",task_id:"task",status:"running"});
 const view=renderHook(()=>useAnalysisStatus("novel","task"),{wrapper});
 await waitFor(()=>expect(view.result.current.status).toBe("running"));
 expect(api.url).toContain("/events/tasks/task");view.unmount();
});
it("已完成任务直接从状态接口读状态，不连接进度流",async()=>{
 api.get.mockResolvedValue({status:"completed"});
 const view=renderHook(()=>useAnalysisStatus("novel","task"),{wrapper});
 await waitFor(()=>expect(view.result.current.status).toBe("completed"));
 expect(api.url).toBeNull();view.unmount();
});
it("失败与已取消任务同样不连接进度流",async()=>{
 api.get.mockResolvedValue({status:"failed"});
 const failed=renderHook(()=>useAnalysisStatus("novel","failed"),{wrapper});
 await waitFor(()=>expect(failed.result.current.status).toBe("failed"));
 expect(api.url).toBeNull();failed.unmount();
 api.get.mockResolvedValue({status:"cancelled"});
 const cancelled=renderHook(()=>useAnalysisStatus("novel","cancelled"),{wrapper});
 await waitFor(()=>expect(cancelled.result.current.status).toBe("cancelled"));
 expect(api.url).toBeNull();cancelled.unmount();
});
it("进度流收到终态事件时立即核对状态接口，状态以接口返回为准",async()=>{
 api.get.mockResolvedValueOnce({status:"running"}).mockResolvedValue({status:"completed"});
 const completed=vi.fn();
 const view=renderHook(()=>useAnalysisStatus("novel","task",{onCompleted:completed}),{wrapper});
 await waitFor(()=>expect(view.result.current.status).toBe("running"));
 act(()=>api.event?.("snapshot",{...emptyAnalysisProjection(),task_id:"task",status:"running"}));
 expect(api.get).toHaveBeenCalledTimes(1);
 act(()=>api.event?.("task_complete",{task_id:"task",status:"completed"},1));
 await waitFor(()=>expect(api.get).toHaveBeenCalledTimes(2));
 await waitFor(()=>expect(view.result.current.status).toBe("completed"));
 expect(completed).toHaveBeenCalledOnce();
 expect(api.url).toBeNull();view.unmount();
});
it("新打开的无效任务读取失败后停止进度流重试",async()=>{
 api.get.mockRejectedValue(new Error('任务不存在'));
 const view=renderHook(()=>useAnalysisStatus('novel','missing'),{wrapper});
 await waitFor(()=>expect(view.result.current.query.isError).toBe(true));
 expect(api.url).toBeNull();view.unmount();
});
