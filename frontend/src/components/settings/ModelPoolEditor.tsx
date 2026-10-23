import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Loader2, Pencil, PlugZap, Plus, RotateCcw, Save, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { testAgentModel, updateModelEnv } from "@/api/settings";
import type { ModelPoolEntry, ModelPoolEntryUpdate, SettingsViewResponse } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

interface ModelPoolEditorProps {
  entries: ModelPoolEntry[];
  diagnosisModelId: string | null;
  onSaved: (view: SettingsViewResponse) => void;
}

interface PoolDraft {
  entries: ModelPoolEntryUpdate[];
  diagnosisModelId: string | null;
}

interface ModelForm {
  model_id: string;
  base_url: string;
  api_key: string;
  weight: string;
  max_in_flight: string;
  temperature: string;
  top_p: string;
  max_tokens: string;
  context_window_tokens: string;
}

/** 模型级参数的表单元数据 */
const MODEL_PARAM_FIELDS = [
  { name: "temperature", label: "温度", min: 0, max: 2, step: "0.1" },
  { name: "top_p", label: "top_p", min: 0, max: 1, step: "0.05" },
  { name: "max_tokens", label: "输出 Token 上限", min: 1, max: null, step: "1" },
  { name: "context_window_tokens", label: "上下文容量", min: 1, max: null, step: "1" },
] as const;

interface ModelDialog {
  index: number | null;
  form: ModelForm;
  error: string;
}

function errorDetail(error: unknown): string {
  if (typeof error === "object" && error !== null && "response" in error) {
    return String((error as { response?: { data?: { detail?: string } } }).response?.data?.detail ?? error);
  }
  return String(error);
}

function initialDraft(entries: ModelPoolEntry[], diagnosisModelId: string | null): PoolDraft {
  return {
    entries: entries.map(({ model_id, base_url, weight, max_in_flight, temperature, top_p, max_tokens, context_window_tokens }) => ({
      model_id, base_url, weight, max_in_flight, temperature, top_p, max_tokens, context_window_tokens,
      original_model_id: model_id,
    })),
    diagnosisModelId,
  };
}

export function ModelPoolEditor({ entries, diagnosisModelId, onSaved }: ModelPoolEditorProps) {
  const [draft, setDraft] = useState<PoolDraft | null>(null);
  const [dialog, setDialog] = useState<ModelDialog | null>(null);
  const [testResult, setTestResult] = useState<string | null>(null);
  const initial = initialDraft(entries, diagnosisModelId);
  const current = draft ?? initial;
  const dirty = JSON.stringify(current) !== JSON.stringify(initial);
  const weightScale = current.entries.reduce((maximum, entry) => Math.max(maximum, entry.weight), 0) || 1;
  const totalWeight = current.entries.reduce((total, entry) => total + entry.weight / weightScale, 0);
  const poolValid = current.entries.some((entry) => entry.weight > 0);
  const diagnosisValid = !current.diagnosisModelId
    || current.entries.some((entry) => entry.model_id === current.diagnosisModelId);

  const save = useMutation({
    mutationFn: () => updateModelEnv({ model_pool: current.entries, diagnosis_model_id: current.diagnosisModelId }),
    onSuccess: (view) => {
      onSaved(view);
      setDraft(null);
      toast.success("模型池已保存");
    },
    onError: (error: unknown) => toast.error(`保存失败：${errorDetail(error)}`),
  });

  const test = useMutation({
    mutationFn: () => {
      if (!dialog) throw new Error("没有正在编辑的模型");
      const entry = dialog.index === null ? null : current.entries[dialog.index];
      return testAgentModel("pool", {
        base_url: dialog.form.base_url.trim(),
        ...(entry?.original_model_id ? { model_id: entry.original_model_id } : {}),
        ...(dialog.form.api_key || entry?.api_key ? { api_key: dialog.form.api_key || entry?.api_key } : {}),
      });
    },
    onSuccess: (result) => setTestResult(result.ok
      ? `连接成功 · ${result.latency_ms ?? "?"}ms`
      : `连接失败：${result.error ?? "未知错误"}`),
    onError: (error: unknown) => setTestResult(`连接失败：${errorDetail(error)}`),
  });

  const openDialog = (index: number | null) => {
    const entry = index === null ? null : current.entries[index];
    setDialog({ index, error: "", form: {
      model_id: entry?.model_id ?? "", base_url: entry?.base_url ?? "", api_key: entry?.api_key ?? "",
      weight: String(entry?.weight ?? 1), max_in_flight: String(entry?.max_in_flight ?? 8),
      temperature: String(entry?.temperature ?? 0.7), top_p: String(entry?.top_p ?? 0.8),
      max_tokens: String(entry?.max_tokens ?? 131072),
      context_window_tokens: String(entry?.context_window_tokens ?? ""),
    } });
    setTestResult(null);
  };

  const submitModel = () => {
    if (!dialog) return;
    const form = dialog.form;
    const modelId = form.model_id.trim();
    let error = "";
    if (!modelId) error = "模型 ID 不能为空";
    else if (current.entries.some((entry, index) => index !== dialog.index && entry.model_id === modelId)) {
      error = "模型 ID 已存在";
    } else {
      try {
        const url = new URL(form.base_url.trim());
        if (!["http:", "https:"].includes(url.protocol) || url.username || url.password || url.search || url.hash) {
          error = "URL 必须是无内嵌凭据的 HTTP 或 HTTPS 服务地址";
        }
      } catch { error = "URL 无效"; }
    }
    const entry = dialog.index === null ? null : current.entries[dialog.index];
    if (!error && !form.api_key.trim() && !entry?.original_model_id) error = "Key 不能为空";
    if (!error && (/[\r\n\0]/.test(form.api_key) || form.api_key.startsWith("••••"))) error = "Key 无效";
    const weight = Number(form.weight);
    const concurrency = Number(form.max_in_flight);
    if (!error && (!form.weight.trim() || !Number.isFinite(weight) || weight < 0)) error = "权重必须是非负数";
    if (!error && (!Number.isInteger(concurrency) || concurrency < 1)) error = "并发必须是正整数";
    const temperature = Number(form.temperature);
    const topP = Number(form.top_p);
    const maxTokens = Number(form.max_tokens);
    const contextWindow = Number(form.context_window_tokens);
    if (!error && (!form.temperature.trim() || !Number.isFinite(temperature) || temperature < 0 || temperature > 2)) {
      error = "温度必须是 [0, 2] 内的数值";
    }
    if (!error && (!form.top_p.trim() || !Number.isFinite(topP) || topP < 0 || topP > 1)) error = "top_p 必须在 [0, 1] 内";
    if (!error && (!Number.isInteger(maxTokens) || maxTokens < 1)) error = "输出 Token 上限必须是正整数";
    if (!error && (!form.context_window_tokens.trim() || !Number.isInteger(contextWindow) || contextWindow < 1)) {
      error = "上下文容量必须是正整数";
    }
    if (error) {
      setDialog({ ...dialog, error });
      return;
    }
    const nextEntry: ModelPoolEntryUpdate = {
      model_id: modelId, base_url: form.base_url.trim().replace(/\/+$/, ""), weight, max_in_flight: concurrency,
      temperature, top_p: topP, max_tokens: maxTokens, context_window_tokens: contextWindow,
      ...(entry?.original_model_id ? { original_model_id: entry.original_model_id } : {}),
      ...(form.api_key ? { api_key: form.api_key } : {}),
    };
    const nextEntries = dialog.index === null ? [...current.entries, nextEntry]
      : current.entries.map((item, index) => index === dialog.index ? nextEntry : item);
    setDraft({ entries: nextEntries, diagnosisModelId: entry?.model_id === current.diagnosisModelId
      ? modelId : current.diagnosisModelId });
    setDialog(null);
  };

  const changeForm = (field: keyof ModelForm, value: string) => {
    if (dialog) setDialog({ ...dialog, error: "", form: { ...dialog.form, [field]: value } });
    setTestResult(null);
  };

  const editedEntry = dialog?.index === null || !dialog ? null : current.entries[dialog.index];
  const savedKey = entries.find((entry) => entry.model_id === editedEntry?.original_model_id)?.api_key;

  return <section aria-label="模型池" className="space-y-4 border-t border-border pt-6">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <h2 className="text-base font-semibold text-text">模型池</h2>
      <div className="flex items-center gap-2">
        {dirty && <IconButton label="放弃模型池修改" disabled={save.isPending} onClick={() => setDraft(null)}>
          <RotateCcw className="h-4 w-4" />
        </IconButton>}
        <Button type="button" variant="outline" size="sm" disabled={save.isPending} onClick={() => openDialog(null)}>
          <Plus className="mr-1 h-4 w-4" />新增模型
        </Button>
        <Button type="button" size="sm" disabled={!dirty || !poolValid || !diagnosisValid || save.isPending}
          onClick={() => save.mutate()}>
          {save.isPending ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <Save className="mr-1 h-4 w-4" />}
          保存模型池
        </Button>
      </div>
    </div>
    {current.entries.length === 0 ? <p className="text-sm text-text-muted">暂无模型</p> : <table className="w-full table-fixed text-left text-sm">
      <thead className="text-text-muted"><tr className="border-b border-border">
        <th className="w-[22%] py-2 font-normal">ID</th><th className="w-[28%] py-2 font-normal">URL</th>
        <th className="w-[10%] py-2 font-normal">Key</th><th className="w-[9%] py-2 font-normal">权重</th>
        <th className="w-[8%] py-2 font-normal">并发</th><th className="w-[12%] py-2 font-normal">上下文</th>
        <th className="w-[11%] py-2"><span className="sr-only">操作</span></th>
      </tr></thead>
      <tbody>{current.entries.map((entry, index) => <tr key={entry.model_id} className="border-b border-border align-top">
        <td className="break-all py-3 pr-3 text-text">{entry.model_id}
          {entry.model_id === current.diagnosisModelId && <Badge variant="secondary" className="mt-1 block w-fit">诊断</Badge>}
        </td>
        <td className="break-all py-3 pr-3 text-text-secondary">{entry.base_url}</td>
        <td className="break-all py-3 pr-2 text-text-muted">{entry.api_key ? "待保存" : entries.find((item) => item.model_id === entry.original_model_id)?.api_key}</td>
        <td className="py-3 tabular-nums">{entry.weight}<span className="block text-xs text-text-muted">
          {(entry.weight / weightScale / (totalWeight || 1) * 100).toFixed(1)}%
        </span></td>
        <td className="py-3 tabular-nums">{entry.max_in_flight}</td>
        <td className="py-3 tabular-nums">{entry.context_window_tokens}</td>
        <td className="py-2"><div className="flex justify-end">
          <IconButton label={`编辑模型：${entry.model_id}`} disabled={save.isPending} onClick={() => openDialog(index)}><Pencil className="h-4 w-4" /></IconButton>
          <IconButton label={`删除模型：${entry.model_id}`} disabled={save.isPending || current.entries.length <= 1}
            onClick={() => setDraft({ entries: current.entries.filter((_, entryIndex) => entryIndex !== index),
              diagnosisModelId: entry.model_id === current.diagnosisModelId ? null : current.diagnosisModelId })}>
            <Trash2 className="h-4 w-4" />
          </IconButton>
        </div></td>
      </tr>)}</tbody>
    </table>}
    {dirty && !poolValid && <p role="alert" className="text-sm text-destructive">至少一个模型的权重必须大于零</p>}
    <div className="grid grid-cols-[160px_minmax(0,1fr)] items-center gap-3">
      <label htmlFor="diagnosis-model" className="text-sm text-text">指定诊断模型</label>
      <Select value={current.diagnosisModelId ?? ""} disabled={save.isPending || current.entries.length === 0}
        onValueChange={(modelId) => setDraft({ ...current, diagnosisModelId: modelId })}>
        <SelectTrigger id="diagnosis-model" className="w-full"><SelectValue placeholder="未指定" /></SelectTrigger>
        <SelectContent>{current.entries.map((entry) => <SelectItem key={entry.model_id} value={entry.model_id}>
          {entry.model_id}
        </SelectItem>)}</SelectContent>
      </Select>
    </div>
    <Dialog open={dialog !== null} onOpenChange={(open) => { if (!open && !test.isPending) setDialog(null); }}>
      <DialogContent>
        <DialogHeader><DialogTitle>{dialog?.index === null ? "新增模型" : "编辑模型"}</DialogTitle></DialogHeader>
        {dialog && <form noValidate onSubmit={(event) => { event.preventDefault(); submitModel(); }} className="space-y-4">
          {(["base_url", "api_key", "model_id", "weight", "max_in_flight"] as const).map((field) => <div key={field} className="space-y-1.5">
            <label htmlFor={`pool-model-${field}`} className="text-sm text-text">
              {{ base_url: "URL", api_key: "Key", model_id: "ID", weight: "权重", max_in_flight: "并发" }[field]}
            </label>
            <Input id={`pool-model-${field}`} type={field === "api_key" ? "password" : field === "weight" || field === "max_in_flight" ? "number" : "text"}
              value={dialog.form[field]} onChange={(event) => changeForm(field, event.target.value)} disabled={test.isPending}
              min={field === "weight" ? 0 : field === "max_in_flight" ? 1 : undefined}
              step={field === "weight" ? "0.1" : field === "max_in_flight" ? "1" : undefined}
              placeholder={field === "api_key" && savedKey ? `已配置（${savedKey}），留空不修改` : undefined}
              autoComplete={field === "api_key" ? "new-password" : "off"} />
          </div>)}
          {MODEL_PARAM_FIELDS.map((field) => <div key={field.name} className="space-y-1.5">
            <label htmlFor={`pool-model-${field.name}`} className="text-sm text-text">{field.label}</label>
            <Input id={`pool-model-${field.name}`} type="number" value={dialog.form[field.name]}
              onChange={(event) => changeForm(field.name, event.target.value)} disabled={test.isPending}
              min={field.min} max={field.max ?? undefined} step={field.step} autoComplete="off" />
          </div>)}
          {dialog.error && <p role="alert" className="text-sm text-destructive">{dialog.error}</p>}
          {testResult && <p role="status" className="break-words text-sm text-text-muted">{testResult}</p>}
          <DialogFooter>
            <Button type="button" variant="outline" disabled={!dialog.form.base_url.trim() || test.isPending}
              onClick={() => test.mutate()}>
              {test.isPending ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <PlugZap className="mr-1 h-4 w-4" />}
              测试连接
            </Button>
            <Button type="submit" disabled={test.isPending}><Plus className="mr-1 h-4 w-4" />
              {dialog.index === null ? "添加" : "应用修改"}
            </Button>
          </DialogFooter>
        </form>}
      </DialogContent>
    </Dialog>
  </section>;
}

function IconButton({ label, children, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  label: string; children: React.ReactNode;
}) {
  return <Tooltip><TooltipTrigger asChild>
    <Button type="button" variant="ghost" size="icon" aria-label={label} {...props}>{children}</Button>
  </TooltipTrigger><TooltipContent>{label}</TooltipContent></Tooltip>;
}
