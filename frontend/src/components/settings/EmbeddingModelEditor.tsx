import { useId, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Loader2, PlugZap, RotateCcw, Save, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { testAgentModel, updateModelEnv } from "@/api/settings";
import type { EmbeddingModelView, ModelEnvUpdate, SettingsViewResponse } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

interface EmbeddingModelForm {
  base_url: string;
  model: string;
  api_key: string;
}

interface EmbeddingModelEditorProps {
  value: EmbeddingModelView;
  onSaved: (view: SettingsViewResponse) => void;
}

function errorDetail(error: unknown): string {
  if (typeof error === "object" && error !== null && "response" in error) {
    return String((error as { response?: { data?: { detail?: string } } }).response?.data?.detail ?? error);
  }
  return String(error);
}

export function EmbeddingModelEditor({
  value, onSaved,
}: EmbeddingModelEditorProps) {
  const inputId = useId();
  const [draft, setDraft] = useState<EmbeddingModelForm | null>(null);
  const [testResult, setTestResult] = useState<string | null>(null);
  const [confirmRemove, setConfirmRemove] = useState(false);
  const initial: EmbeddingModelForm = { base_url: value.base_url ?? "", model: value.model ?? "", api_key: "" };
  const form = draft ?? initial;
  const dirty = JSON.stringify(form) !== JSON.stringify(initial);
  const title = "嵌入模型";

  const payload = (clear: boolean): ModelEnvUpdate => {
    const patch = clear
      ? { api_key: "" }
      : { base_url: form.base_url.trim(), model: form.model.trim(),
          api_key: form.api_key || null };
    return { embedding_model: patch };
  };

  const save = useMutation({
    mutationFn: (clear: boolean) => updateModelEnv(payload(clear)),
    onSuccess: (view, clear) => {
      onSaved(view);
      setDraft(null);
      setTestResult(null);
      setConfirmRemove(false);
      toast.success(clear ? "凭据已清空" : "连接配置已保存");
    },
    onError: (error: unknown) => toast.error(`保存失败：${errorDetail(error)}`),
  });

  const test = useMutation({
    mutationFn: () => testAgentModel("embedding", {
      base_url: form.base_url.trim(),
      ...(form.api_key ? { api_key: form.api_key } : {}),
    }),
    onSuccess: (result) => setTestResult(result.ok
      ? `连接成功 · ${result.latency_ms ?? "?"}ms · ${result.model_ids.length} 个模型`
      : `连接失败：${result.error ?? "未知错误"}`),
    onError: (error: unknown) => setTestResult(`连接失败：${errorDetail(error)}`),
  });

  const change = (field: keyof EmbeddingModelForm, next: string) => {
    setDraft({ ...form, [field]: next });
    setTestResult(null);
  };

  return (
    <section role="region" aria-label={title} className="space-y-3 border-t border-border py-4">
      <div className="flex flex-row flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <h2 className="text-base font-semibold">{title}</h2>
          <Badge variant="secondary">{value.configured ? "已配置" : "未配置"}</Badge>
        </div>
        <div className="flex items-center gap-2">
          {dirty && (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button type="button" variant="ghost" size="icon" aria-label={`放弃修改：${title}`}
                  disabled={save.isPending || test.isPending} onClick={() => { setDraft(null); setTestResult(null); }}>
                  <RotateCcw className="h-4 w-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>放弃修改</TooltipContent>
            </Tooltip>
          )}
          <Button type="button" variant="outline" size="sm" onClick={() => test.mutate()}
            disabled={!form.base_url.trim() || test.isPending || save.isPending}>
            {test.isPending ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <PlugZap className="mr-1 h-4 w-4" />}
            测试连接
          </Button>
          <Button type="button" size="sm" onClick={() => save.mutate(false)}
            disabled={!dirty || !form.base_url.trim() || !form.model.trim() || save.isPending || test.isPending}>
            {save.isPending ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <Save className="mr-1 h-4 w-4" />}
            保存凭据
          </Button>
          <Tooltip>
            <TooltipTrigger asChild>
              <span className="inline-flex">
                <Button type="button" variant="ghost" size="icon" aria-label={`清空凭据：${title}`}
                  disabled={save.isPending || test.isPending}
                  onClick={() => setConfirmRemove(true)}>
                  <Trash2 className="h-4 w-4" />
                </Button>
              </span>
            </TooltipTrigger>
            <TooltipContent>{`清空凭据：${title}`}</TooltipContent>
          </Tooltip>
        </div>
      </div>
      <div className="space-y-3">
        {(["base_url", "model", "api_key"] as const).map((field) => {
          const label = { base_url: "Base URL", model: "模型 ID", api_key: "API Key" }[field];
          return (
            <div key={field} className="grid grid-cols-[160px_minmax(0,1fr)] items-center gap-3">
              <label className="text-sm text-text" htmlFor={`${inputId}-${field}`}>{label}</label>
              <Input id={`${inputId}-${field}`} type={field === "api_key" ? "password" : "text"}
                value={form[field]} onChange={(event) => change(field, event.target.value)}
                disabled={save.isPending || test.isPending}
                placeholder={field === "api_key"
                  ? value.api_key ? `已配置（${value.api_key}），留空不修改` : "未配置"
                  : undefined}
                autoComplete={field === "api_key" ? "new-password" : "off"} />
            </div>
          );
        })}
        {testResult && <p role="status" className="text-xs text-text-muted break-words">{testResult}</p>}
      </div>
      <Dialog open={confirmRemove} onOpenChange={setConfirmRemove}>
        <DialogContent>
          <DialogHeader><DialogTitle>清空 {title} 的凭据？</DialogTitle></DialogHeader>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setConfirmRemove(false)}>取消</Button>
            <Button type="button" variant="destructive" disabled={save.isPending} onClick={() => save.mutate(true)}>
              <Trash2 className="mr-1 h-4 w-4" />清空凭据
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}
