/** 六阶段共用一个工作台，只有真实 Agent 阶段展开工位 */
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { useStreamStore } from "@/store/streamStore";
import { analysisStages, type ProgressRecord } from "@/store/analysisProjection";
import { AgentOffice } from "./AgentOffice";
import { ExecutionDetails } from "./ExecutionDetails";
import { failureNotice } from "./failureNotice";
import { executionSummary, progressName } from "./workbenchLabels";

const names: Record<string, string> = { preprocess: "预处理", annotate: "章节标注", linguistic: "语言分析", aggregate: "聚合统计", "topic-model": "主题建模", diagnose: "全书诊断" };
const states: Record<string, string> = { not_in_scope: "本次不执行", pending: "等待执行", running: "执行中", completed: "已完成", skipped: "已跳过", disabled: "已禁用", saving: "保存中", cancelled: "已停止", cancelling: "停止收尾中", failed: "执行失败" };
const interruptedStatuses = ["failed", "cancelled", "cancelling"];
function count(step: ProgressRecord, stageStatus?: string) {
  if (step.current == null && ["running", "saving"].includes(step.status ?? "")) {
    if (stageStatus === "cancelled") return "已停止 · 完成状态未记录";
    if (stageStatus === "failed") return "已中断 · 完成状态未记录";
  }
  return step.current == null ? states[step.status ?? ""] ?? "未记录" : `${step.current}${step.total == null ? "" : ` / ${step.total}`} ${step.unit ?? ""}`;
}
export function AnalysisWorkbench({ taskId, onCancel, onResume }: { taskId: string; onCancel: () => void | Promise<void>; onResume: () => void | Promise<void> }) {
  const projection = useStreamStore(s => s.projection), status = useStreamStore(s => s.status), connected = useStreamStore(s => s.isConnected);
  const ready = useStreamStore(s => s.snapshotReady), warning = useStreamStore(s => s.notificationWarning);
  const selected = useStreamStore(s => s.selectedInvocation), pinned = useStreamStore(s => s.pinnedExecution);
  const select = useStreamStore(s => s.selectExecution);
  const [expanded, setExpanded] = useState<{ stage: string; key: string } | null>(null);
  const [cancelRequested, setCancelRequested] = useState(false);
  const [seatNotice, setSeatNotice] = useState<string>();
  const records = Object.values(projection.executions);
  if (pinned && !records.some(item => item.invocation_id === pinned.invocation_id)) records.unshift(pinned);
  const current = projection.stage, open = expanded?.stage === current ? expanded.key : current;
  const execution = (selected && projection.executions[selected]) || pinned;
  const selectedRecord = records.find(item => item.invocation_id === selected);
  const seated = !!execution && projection.seats.some(s => !s.foreign && s.reservation_id === execution.reservation_id);
  const recoverable = status === "failed" || status === "cancelled";
  const stopping = status === "cancelling";
  const interrupted = interruptedStatuses.includes(status ?? "");
  const failure = failureNotice(projection.error);
  return <section className="min-w-0 pb-5" aria-label="分析工作台">
    <div className="mb-5 flex items-center justify-between gap-5"><div><div className="text-xs tracking-widest text-text-muted">ANALYSIS WORKSPACE</div><h2 className="mt-1 text-2xl font-medium text-text">全书分析</h2></div><div className="flex items-center gap-5"><span className="text-xs text-text-muted">{connected ? '实时连接正常' : '连接断开，正在重连'}</span><Button size="sm" variant={recoverable ? 'default' : 'outline'} disabled={cancelRequested || stopping || status === 'completed' || !status} onClick={async () => { setCancelRequested(true); try { await (recoverable ? onResume() : onCancel()); } finally { setCancelRequested(false); } }}>{cancelRequested ? '请求处理中' : recoverable ? '恢复分析' : stopping ? '正在停止' : '停止分析'}</Button></div></div>
    <div className="mb-4 flex justify-between gap-5 border-t border-border pt-3 text-xs text-text-muted"><span>当前阶段 <span className="ml-2 text-text">{names[current] || '未记录'}</span> · {stopping ? '停止收尾中' : states[status ?? ''] || '同步任务状态'}</span><code>{taskId}</code></div>
    {(recoverable || stopping || projection.error || warning) && <div className="mb-4 rounded-lg bg-primary-subtle px-4 py-3 text-sm text-text" role={warning || projection.error ? 'alert' : 'status'}>
      {warning ? `通知保存失败，持续告警并重试：${warning}` : failure ? <>
        <p>{failure.title}</p>
        {failure.detail && <details className="mt-2"><summary className="cursor-pointer text-xs text-text-muted">查看原始错误</summary><pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap break-all text-xs leading-5 text-text-muted">{failure.detail}</pre></details>}
      </> : stopping ? '正在取消执行并等待保存收尾，工位随实际容量释放更新。' : '执行记录已保留，可恢复分析。'}
    </div>}
    {status === 'completed' && <div className="mb-4 text-sm text-text-muted">{!ready || projection.sync_pending ? '业务已完成，正在同步最终执行记录。' : '分析已完成，执行记录已同步。'}</div>}
    {!ready && <div className="mb-4 text-sm text-text-muted" role="status">正在读取执行快照…</div>}
    <div className="overflow-hidden rounded-xl border border-border bg-surface">
      {analysisStages.map((key, i) => {
        const stage = projection.stages[key], isCurrent = key === current, isOpen = key === open;
        const steps = Object.entries(stage?.steps ?? {});
        const unfinished = interrupted && stage?.status === 'pending';
        const summary = steps.length ? steps.map(([name, p]) => `${progressName(name)} ${count(p, stage?.status)}`).join(' · ') : unfinished ? '未执行' : stage?.message || '过程未记录';
        const statusLabel = unfinished ? '未执行' : states[stage?.status ?? ''] || '未记录';
        const office = (key === 'annotate' || key === 'diagnose') && isCurrent;
        return <section key={key} className={`border-b border-border last:border-b-0 ${isCurrent ? 'border-l-[3px] border-l-primary bg-primary-subtle/20' : ''}`} data-analysis-stage={key}>
          <button type="button" className="grid w-full grid-cols-[28px_110px_minmax(0,1fr)_90px] items-center gap-3 px-5 py-4 text-left" aria-expanded={isOpen} onClick={() => setExpanded({ stage: current, key: isOpen ? '' : key })}><span className="text-xs tabular-nums text-text-muted">{stage?.status === 'completed' ? '✓' : String(i + 1).padStart(2, '0')}</span><span className="text-sm font-medium text-text">{names[key]}</span><span className="truncate text-xs text-text-muted" title={summary}>{summary}</span><span className={`text-right text-xs ${isCurrent ? 'text-primary' : 'text-text-muted'}`}>{statusLabel}</span></button>
          {isOpen && (office ? <div className="px-5 pb-4">
            <div className="mb-3 flex flex-wrap gap-x-5 gap-y-1 text-xs text-text-muted">{projection.models.map(m => <span key={m.model_id} className="break-all">{m.model_id} <span className="ml-2 tabular-nums">{projection.seats.filter(s => s.model_id === m.model_id).length} / {m.capacity}</span></span>)}</div>
            <div className="grid grid-cols-[minmax(0,1fr)_320px] border-y border-border">
              <AgentOffice models={projection.models} seats={projection.seats} executions={projection.executions} selected={selected} onSelect={(id, seat) => { select(id); setSeatNotice(seat?.foreign ? "此工位由其他任务占用，执行内容不在当前任务中。" : seat ? "容量已预留，Agent 尚未启动。" : "此工位空闲。"); }} />
              <aside className="min-w-0 border-l border-border">
                <div className="border-b border-border px-4 py-3">
                  <label className="mb-1 block text-xs text-text-muted" htmlFor="execution-history">执行记录</label>
                  <select id="execution-history" aria-label="选择执行记录" className="w-full min-w-0 rounded border border-border bg-surface px-2 py-1 text-xs text-text" title={selectedRecord ? `${executionSummary(selectedRecord)}·${selectedRecord.invocation_id}` : undefined} value={selected ?? ""} onChange={event => { select(event.target.value || null); setSeatNotice(undefined); }}><option value="">选择工位或历史执行</option>{records.map(record => <option key={record.invocation_id} value={record.invocation_id}>{executionSummary(record)}·{record.invocation_id.slice(-8)}</option>)}</select>
                </div>
                <ExecutionDetails execution={execution} seated={seated} emptyMessage={seatNotice} />
              </aside>
            </div>
            <div className="mt-3 flex justify-between text-xs text-text-muted"><span>本任务 {projection.seats.filter(s => !s.foreign).length} 席 · 其他任务 {projection.seats.filter(s => s.foreign).length} 席</span><span>排队不占工位</span></div>
          </div> : <div className="pb-5 pl-[60px] pr-5">
            {steps.length ? <div className="flex flex-wrap gap-x-9 gap-y-4">{steps.map(([name, p]) => <div key={name} className="min-w-[180px] flex-1">
              <div className="flex justify-between gap-4 text-xs"><span className="text-text">{progressName(name)}</span><span className="tabular-nums text-text-muted">{count(p, stage?.status)}</span></div>
              {p.current != null && p.total != null && p.total > 0 ? <div className="mt-3 h-[3px] overflow-hidden rounded bg-border"><div className="h-full bg-primary" style={{ width: `${Math.min(100, p.current / p.total * 100)}%` }} /></div> : <div className="mt-3 text-xs text-text-muted">{p.message || '细分进度未记录'}</div>}
            </div>)}</div> : <p className="text-xs text-text-muted">{stage?.message || (unfinished ? '未执行，没有过程记录' : '此阶段没有已记录的过程信息')}</p>}
          </div>)}
        </section>;
      })}
    </div><div className="mt-4 flex justify-between text-xs text-text-muted"><span>完成计数以正式保存为准</span><span>执行记录按实际身份保留</span></div>
  </section>;
}
