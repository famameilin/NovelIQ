/** 选定执行的有界输出、推理与真实工具调用 */
import {useState} from "react";
import type {ExecutionRecord} from "@/store/analysisProjection";
import {executionRole, executionActivity} from "./workbenchLabels";

export function ExecutionDetails({execution,seated,emptyMessage}:{execution:ExecutionRecord|null;seated:boolean;emptyMessage?:string}) {
  const [tab,setTab]=useState("output");
  if(!execution)return <div className="p-5 text-sm text-text-muted">{emptyMessage??"点击工位或选择执行记录，查看当前及已结束的 Agent。"}</div>;
  return <div className="h-[369px] overflow-y-auto p-5">
    <div className="mb-3 text-xs text-text-muted">执行详情 · {seated?"工位执行中":"已离座，详情保留"}</div>
    <div className="font-medium text-text">{executionRole(execution.sub_stage)}</div>
    <div className="mt-1 break-all text-xs leading-6 text-text-muted">{execution.model_id||"模型未记录"}<br />{execution.chapter_id?`章节 ${execution.chapter_id}`:execution.sub_stage==="case"?"案例会话":""}<br /><code>{execution.invocation_id}</code></div>
    {execution.details?.case_ids?.length? <div className="mt-2 break-all text-xs text-text-muted">已领取案例：{execution.details.case_ids.join("、")}</div>:null}
    <div className="my-4 flex gap-5 border-b border-border" role="tablist" aria-label="执行详情内容">
      {[['output','模型输出'],['thinking','思考'],['tools','工具调用']].map(([id,label])=><button key={id} type="button" role="tab" aria-selected={tab===id} className={`border-b-2 pb-2 text-xs ${tab===id?"border-primary text-text":"border-transparent text-text-muted"}`} onClick={()=>setTab(id)}>{label}</button>)}
    </div>
    <div className={`mb-2 text-xs ${execution.activity==="error"?"text-chart-negative":"text-primary"}`}>{executionActivity(execution.activity)}</div>
    {execution.error&&<p className="mb-3 text-sm text-chart-negative">{execution.error}</p>}
    {execution.truncated&&<p className="mb-2 text-xs text-text-muted">较早输出已截断，当前保留末尾内容</p>}
    <div className="whitespace-pre-wrap break-words text-sm leading-7 text-text" role="tabpanel">
      {tab==='tools'?Object.values(execution.tools).length?Object.values(execution.tools).map(tool=><div className="mb-3" key={tool.tool_call_id}><span>{tool.content} · {tool.status==='success'?'成功':tool.status==='failed'?'失败':'执行中'}</span><div className="text-xs text-text-muted">{tool.message}</div></div>):"未记录工具调用":execution[tab==='thinking'?'thinking':'output']||"暂无记录"}
    </div>
  </div>;
}
