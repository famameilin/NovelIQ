/**
 * 设置页 —— schema 驱动表单 + 模型凭据编辑 + 恢复默认
 *
 * 两条数据通道（与后端 /api/settings/* 契约一致）：
 * - 参数表单：按字段注册表自动渲染，保存 PUT /api/settings（稀疏化写 settings.json，热生效）
 * - 模型凭据：.env 单源的受控编辑器，保存 PUT /api/settings/env（api_key 只写不读，回显打码）
 *
 * 表单常驻可编辑：首次修改/恢复默认时从服务端值懒创建草稿，
 * 保存前不落盘；建库维度字段不可编辑也不提供恢复默认。
 */
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, RotateCcw, Save } from "lucide-react";
import { toast } from "sonner";
import {
  getSettings,
  getSettingsSchema,
  settingsQueryKey,
  updateModelEnv,
  updateSettings,
} from "@/api/settings";
import type { ModelPoolEntry, SettingFieldSpec } from "@/api/types";
import { ModelProviderEditor } from "@/components/settings/ModelProviderEditor";
import { ModelPoolEditor } from "@/components/settings/ModelPoolEditor";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";

type Json = Record<string, unknown>;

function getPath(obj: unknown, path: string[]): unknown {
  let current: unknown = obj;
  for (const segment of path) {
    if (typeof current !== "object" || current === null || !(segment in current)) {
      return undefined;
    }
    current = (current as Json)[segment];
  }
  return current;
}

function setPath(obj: Json, path: string[], value: unknown): Json {
  const [head, ...rest] = path;
  if (rest.length === 0) {
    return { ...obj, [head]: value };
  }
  const child = (typeof obj[head] === "object" && obj[head] !== null ? (obj[head] as Json) : {}) as Json;
  return { ...obj, [head]: setPath(child, rest, value) };
}

function deepClone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

const MODEL_GROUP_TITLES: Record<string, string> = {
  annotation: "标注", diagnosis: "诊断", paragraph_embedding: "段落嵌入",
};

export function SettingsPage() {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<Json | null>(null);
  const [ltpDraft, setLtpDraft] = useState<string | null>(null);

  const schemaQuery = useQuery({ queryKey: ["settings", "schema"], queryFn: getSettingsSchema });
  const viewQuery = useQuery({
    queryKey: settingsQueryKey,
    queryFn: getSettings,
  });

  const values = viewQuery.data?.values ?? null;
  const defaults = viewQuery.data?.defaults ?? null;

  const ltpModelDir = ltpDraft ?? String(getPath(values, ["linguistic", "ltp", "model_dir"]) ?? "");
  const modelPool = (getPath(values, ["models", "model_pool"]) ?? []) as ModelPoolEntry[];
  const diagnosisModelId = getPath(values, ["models", "diagnosis_model_id"]) as string | null;

  const fieldsBySection = useMemo(() => {
    const grouped: Record<string, SettingFieldSpec[]> = {};
    for (const spec of schemaQuery.data?.fields ?? []) {
      (grouped[spec.path[0]] ??= []).push(spec);
    }
    return grouped;
  }, [schemaQuery.data]);

  const isDirty = useMemo(() => {
    if (!draft || !values) return false;
    return (schemaQuery.data?.fields ?? []).some((spec) =>
      JSON.stringify(getPath(draft, spec.path)) !== JSON.stringify(getPath(values, spec.path)));
  }, [draft, values, schemaQuery.data]);

  /** 常驻可编辑：首次修改/恢复默认时从服务端值懒创建草稿 */
  const ensureDraft = (): Json | null => {
    if (draft) return draft;
    if (!values) return null;
    const base = deepClone(values);
    setDraft(base);
    return base;
  };

  const saveMutation = useMutation({
    mutationFn: () => updateSettings(changedValues(values as Json, draft as Json, schemaQuery.data?.fields ?? [])),
    onSuccess: (data) => {
      setDraft(null);
      queryClient.setQueryData(settingsQueryKey, data);
      toast.success("设置已保存并生效");
    },
    onError: (error: unknown) => {
      const detail =
        typeof error === "object" && error !== null && "response" in error
          ? String((error as { response?: { data?: { detail?: string } } }).response?.data?.detail ?? error)
          : String(error);
      toast.error(`保存失败：${detail}`);
    },
  });

  const envMutation = useMutation({
    mutationFn: () => updateModelEnv({ ltp_model_dir: ltpModelDir }),
    onSuccess: (data) => {
      setLtpDraft(null);
      queryClient.setQueryData(settingsQueryKey, data);
      toast.success("LTP 模型目录已保存");
    },
    onError: (error: unknown) => {
      const detail =
        typeof error === "object" && error !== null && "response" in error
          ? String((error as { response?: { data?: { detail?: string } } }).response?.data?.detail ?? error)
          : String(error);
      toast.error(`保存失败：${detail}`);
    },
  });

  const resetField = (spec: SettingFieldSpec) => {
    const base = ensureDraft();
    if (!base) return;
    const fallback = fieldFallback(spec);
    const storedDefault = getPath(defaults, spec.path);
    const defaultValue = storedDefault === undefined ? fallback : storedDefault;
    setDraft(setPath(deepClone(base), spec.path, defaultValue));
  };

  const resetSection = (sectionId: string) => {
    const base = ensureDraft();
    if (!base || !defaults) return;
    let next = deepClone(base);
    for (const spec of schemaQuery.data?.fields.filter((item) => item.path[0] === sectionId) ?? []) {
      if (!spec.editable) continue;
      const storedDefault = getPath(defaults, spec.path);
      next = setPath(next, spec.path, storedDefault === undefined ? fieldFallback(spec) : storedDefault);
    }
    setDraft(next);
  };

  const updateField = (spec: SettingFieldSpec, raw: string | boolean) => {
    const base = ensureDraft();
    if (!base) return;
    let value: unknown = raw;
    if (spec.field_type === "number" || spec.field_type === "integer") {
      if (raw === "") {
        value = spec.nullable ? null : undefined;
      } else {
        const parsed = Number(raw);
        value = !Number.isFinite(parsed) || (spec.field_type === "integer" && !Number.isInteger(parsed)) ? undefined : parsed;
      }
    }
    if (value === undefined) return;
    setDraft(setPath(deepClone(base), spec.path, value));
  };

  if (schemaQuery.isLoading || viewQuery.isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-text-muted" />
      </div>
    );
  }

  if (schemaQuery.isError || viewQuery.isError || !values || !defaults) {
    return (
      <div className="flex h-full items-center justify-center text-text-muted">
        设置加载失败，请确认后端服务可用
      </div>
    );
  }

  const sections = schemaQuery.data?.sections ?? [];
  const embedding = (getPath(values, ["models", "paragraph_embedding"]) ?? {}) as Json;

  return (
    <div className="mx-auto w-full max-w-4xl space-y-6 px-6 py-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-text">设置</h1>
        </div>
        <div className="flex items-center gap-2">
          {isDirty && (
            <Button type="button" variant="ghost" onClick={() => setDraft(null)} disabled={saveMutation.isPending}>
              放弃修改
            </Button>
          )}
          <Button
            type="button"
            onClick={() => saveMutation.mutate()}
            disabled={!isDirty || saveMutation.isPending}
          >
            {saveMutation.isPending ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <Save className="mr-1 h-4 w-4" />}
            保存设置
          </Button>
        </div>
      </div>

      {isDirty && (
        <div className="rounded-md border border-primary/40 bg-primary-subtle px-4 py-2 text-sm text-text">
          有未保存的修改，保存后立即生效。
        </div>
      )}

      <ModelPoolEditor entries={modelPool} diagnosisModelId={diagnosisModelId}
        onSaved={(view) => queryClient.setQueryData(settingsQueryKey, view)} />

      <ModelProviderEditor value={{
        base_url: embedding.base_url as string | null,
        model: embedding.model as string | null,
        api_key: embedding.api_key as string | null,
        configured: Boolean(embedding.base_url && embedding.model && embedding.api_key),
      }} onSaved={(view) => queryClient.setQueryData(settingsQueryKey, view)} />

      <section className="space-y-3 border-t border-border py-4" aria-label="LTP 模型目录">
        <h2 className="text-base font-semibold text-text">LTP 模型目录</h2>
        <div className="grid grid-cols-[180px_minmax(0,1fr)_auto] items-center gap-3">
            <label htmlFor="ltp-model-dir" className="text-sm text-text">模型目录</label>
            <Input id="ltp-model-dir" value={ltpModelDir} onChange={(event) => setLtpDraft(event.target.value)} placeholder="未配置" />
            <Button type="button" onClick={() => envMutation.mutate()} disabled={ltpDraft === null || envMutation.isPending}>
              {envMutation.isPending && <Loader2 className="mr-1 h-4 w-4 animate-spin" />}
              <Save className="mr-1 h-4 w-4" />保存目录
            </Button>
        </div>
      </section>

      {sections.map((section) => {
        const sectionFields = fieldsBySection[section.id] ?? [];
        if (sectionFields.length === 0) return null;
        return (
          <section key={section.id} className="space-y-4 border-t border-border pt-6" aria-label={section.title}>
            <div className="flex items-start justify-between gap-3">
              <h2 className="text-base font-semibold text-text">{section.title}</h2>
              <Button type="button" variant="ghost" size="sm" onClick={() => resetSection(section.id)}>
                <RotateCcw className="mr-1 h-3.5 w-3.5" />
                恢复默认
              </Button>
            </div>
            <div className="space-y-4">
              {sectionFields.map((spec, index) => (
                <div key={spec.path.join("/")}>
                  {section.id === "models" && (index === 0 || sectionFields[index - 1].path[1] !== spec.path[1]) && (
                    <h3 className="mb-4 pt-2 text-sm font-semibold text-text-secondary">{MODEL_GROUP_TITLES[spec.path[1]]}</h3>
                  )}
                <SettingFieldRow
                  spec={spec}
                  values={draft ?? values}
                  defaults={defaults}
                  onChange={(raw) => updateField(spec, raw)}
                  onReset={() => resetField(spec)}
                />
                </div>
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}

function changedValues(before: Json, after: Json, fields: SettingFieldSpec[]): Json {
  let result: Json = {};
  for (const spec of fields) {
    if (!spec.editable) continue;
    const value = getPath(after, spec.path);
    if (JSON.stringify(value) !== JSON.stringify(getPath(before, spec.path))) result = setPath(result, spec.path, value);
  }
  return result;
}

/** 开放键空间字段（如 logging.modules.*）在 defaults 中无对应叶子时的中性回退 */
function fieldFallback(spec: SettingFieldSpec): unknown {
  switch (spec.field_type) {
    case "boolean":
      return false;
    case "enum":
      return spec.enum_values[0] ?? "";
    case "number":
    case "integer":
      return spec.min_value ?? 0;
    default:
      return "";
  }
}

interface SettingFieldRowProps {
  spec: SettingFieldSpec;
  values: Json;
  defaults: Json;
  onChange: (raw: string | boolean) => void;
  onReset: () => void;
}

function SettingFieldRow({ spec, values, defaults, onChange, onReset }: SettingFieldRowProps) {
  const current = getPath(values, spec.path);
  const defaultValue = getPath(defaults, spec.path);
  const displayDefault =
    defaultValue === undefined ? fieldFallback(spec) : defaultValue;
  const inputId = `setting-${spec.path.join("-")}`;

  return (
    <div className="grid grid-cols-[240px_minmax(0,1fr)_auto] items-center gap-3">
      <div>
        <label htmlFor={inputId} className="block text-sm text-text">{spec.label}</label>
        {spec.description && <span className="block text-xs text-text-muted">{spec.description}</span>}
      </div>
      <div className="flex items-center gap-2">
        <FieldControl spec={spec} value={current} onChange={onChange} defaultValue={displayDefault} inputId={inputId} />
        {!spec.editable && <Badge variant="secondary">建库维度</Badge>}
      </div>
      <div className="flex items-center gap-1.5">
        {spec.editable && (
          <Button type="button" variant="ghost" size="icon" aria-label={`恢复默认：${spec.label}`} onClick={onReset}>
            <RotateCcw className="h-3.5 w-3.5" />
          </Button>
        )}
      </div>
    </div>
  );
}

interface FieldControlProps {
  spec: SettingFieldSpec;
  value: unknown;
  onChange: (raw: string | boolean) => void;
  defaultValue: unknown;
  inputId: string;
}

function FieldControl({ spec, value, onChange, defaultValue, inputId }: FieldControlProps) {
  const className = "max-w-[280px]";
  switch (spec.field_type) {
    case "boolean":
      return <Switch id={inputId} checked={Boolean(value)} onCheckedChange={(checked) => onChange(checked)} />;
    case "enum": {
      const stringValue = String(value ?? "");
      return (
        <Select value={stringValue} onValueChange={(next) => onChange(next)}>
          <SelectTrigger id={inputId} className={className}>
            <SelectValue placeholder="选择" />
          </SelectTrigger>
          <SelectContent>
            {spec.enum_values.map((item) => (
              <SelectItem key={item} value={item}>
                {item}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      );
    }
    case "number":
    case "integer": {
      const text = value === null || value === undefined ? "" : String(value);
      return (
        <Input
          id={inputId}
          type="number"
          className={className}
          value={text}
          min={spec.min_value ?? undefined}
          max={spec.max_value ?? undefined}
          step={spec.step ?? (spec.field_type === "integer" ? 1 : undefined)}
          placeholder={defaultValue === null ? "未设置" : `默认 ${String(defaultValue)}`}
          onChange={(e) => onChange(e.target.value)}
        />
      );
    }
    default:
      return (
        <Input
          id={inputId}
          className={className}
          value={String(value ?? "")}
          placeholder={`默认 ${String(defaultValue)}`}
          onChange={(e) => onChange(e.target.value)}
        />
      );
  }
}
