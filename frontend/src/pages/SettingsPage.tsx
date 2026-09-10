/**
 * 设置页 —— schema 驱动表单 + 模型凭据编辑 + 恢复默认
 *
 * 三条数据通道（与后端 /api/settings/* 契约一致）：
 * - 参数表单：按字段注册表自动渲染，保存 PUT /api/settings（稀疏化写 settings.json，热生效）
 * - 模型凭据：.env 单源的受控编辑器，保存 PUT /api/settings/env（api_key 只写不读，回显打码）
 * - JSON 预览：当前表单值的只读快照 + 复制
 */
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, RotateCcw, PlugZap, Copy } from "lucide-react";
import { toast } from "sonner";
import {
  getSettings,
  getSettingsSchema,
  settingsQueryKey,
  testModelProvider,
  updateModelEnv,
  updateSettings,
} from "@/api/settings";
import type { SettingFieldSpec } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";

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

/** 凭据打码值前缀（与后端 _API_KEY_MASK_PREFIX 一致） */
const API_KEY_MASK_PREFIX = "••••";

interface ProviderFormState {
  base_url: string;
  model: string;
  api_key: string;
}

const EMPTY_PROVIDER: ProviderFormState = { base_url: "", model: "", api_key: "" };

export function SettingsPage() {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<Json | null>(null);
  const [showJson, setShowJson] = useState(false);
  const [textProvider, setTextProvider] = useState<ProviderFormState>(EMPTY_PROVIDER);
  const [embeddingProvider, setEmbeddingProvider] = useState<ProviderFormState>(EMPTY_PROVIDER);
  const [ltpModelDir, setLtpModelDir] = useState("");
  const [testResult, setTestResult] = useState<Record<string, string>>({});

  const schemaQuery = useQuery({ queryKey: ["settings", "schema"], queryFn: getSettingsSchema });
  const viewQuery = useQuery({
    queryKey: settingsQueryKey,
    queryFn: getSettings,
    select: (data) => {
      // 凭据初值只随服务端数据首次进入表单态
      return data;
    },
  });

  const values = viewQuery.data?.values ?? null;
  const defaults = viewQuery.data?.defaults ?? null;
  const sources = viewQuery.data?.sources ?? {};

  const model = useMemo(() => values as Json | null, [values]);

  // 凭据表单初值：仅在服务端数据首次到达（或保存后重置）时同步一次，
  // 避免用户编辑中的凭据输入被查询刷新覆盖；api_key 永远以空值表示"不修改"
  const [providerSeeded, setProviderSeeded] = useState(false);
  useEffect(() => {
    if (!model || providerSeeded) return;
    const annotation = (getPath(model, ["models", "annotation"]) ?? {}) as Json;
    const embedding = (getPath(model, ["models", "paragraph_embedding"]) ?? {}) as Json;
    setTextProvider({
      base_url: String(annotation.base_url ?? ""),
      model: String(annotation.model ?? ""),
      api_key: "",
    });
    setEmbeddingProvider({
      base_url: String(embedding.base_url ?? ""),
      model: String(embedding.model ?? ""),
      api_key: "",
    });
    setLtpModelDir(String(getPath(model, ["linguistic", "ltp", "model_dir"]) ?? ""));
    setProviderSeeded(true);
  }, [model, providerSeeded]);

  const fieldsBySection = useMemo(() => {
    const grouped: Record<string, SettingFieldSpec[]> = {};
    for (const spec of schemaQuery.data?.fields ?? []) {
      (grouped[spec.path[0]] ??= []).push(spec);
    }
    return grouped;
  }, [schemaQuery.data]);

  const isDirty = useMemo(() => {
    if (!draft || !values) return false;
    return JSON.stringify(draft) !== JSON.stringify(values);
  }, [draft, values]);

  const saveMutation = useMutation({
    mutationFn: () => updateSettings(draft as Json),
    onSuccess: (data) => {
      setDraft(null);
      setProviderSeeded(false);
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
    mutationFn: () =>
      updateModelEnv({
        model: { ...textProvider, api_key: textProvider.api_key || null },
        embedding_model: { ...embeddingProvider, api_key: embeddingProvider.api_key || null },
        ltp_model_dir: ltpModelDir,
      }),
    onSuccess: (data) => {
      setProviderSeeded(false);
      queryClient.setQueryData(settingsQueryKey, data);
      toast.success("模型凭据已保存并生效");
    },
    onError: (error: unknown) => {
      const detail =
        typeof error === "object" && error !== null && "response" in error
          ? String((error as { response?: { data?: { detail?: string } } }).response?.data?.detail ?? error)
          : String(error);
      toast.error(`保存失败：${detail}`);
    },
  });

  const testMutation = useMutation({
    mutationFn: async ({ task, baseUrl }: { task: "annotation" | "embedding"; baseUrl: string }) => {
      return testModelProvider(task, baseUrl ? { base_url: baseUrl } : undefined);
    },
    onSuccess: (data, variables) => {
      const label = variables.task === "annotation" ? "文本模型" : "嵌入模型";
      setTestResult((prev) => ({
        ...prev,
        [variables.task]: data.ok
          ? `连接成功（${data.latency_ms ?? "?"}ms，${data.model_ids.length} 个模型）`
          : `连接失败：${data.error ?? "未知错误"}`,
      }));
      toast[data.ok ? "success" : "error"](`${label}${data.ok ? "连接成功" : "连接失败"}`);
    },
  });

  const startEditing = () => {
    if (values) setDraft(deepClone(values));
  };

  const resetField = (spec: SettingFieldSpec) => {
    if (!draft) return;
    const fallback = fieldFallback(spec);
    const defaultValue = getPath(defaults, spec.path) ?? fallback;
    setDraft(setPath(deepClone(draft), spec.path, defaultValue));
  };

  const resetSection = (sectionId: string) => {
    if (!draft || !defaults) return;
    let next = deepClone(draft);
    for (const spec of fieldsBySection[sectionId] ?? []) {
      next = setPath(next, spec.path, getPath(defaults, spec.path) ?? fieldFallback(spec));
    }
    setDraft(next);
  };

  const updateField = (spec: SettingFieldSpec, raw: string | boolean) => {
    if (!draft) return;
    let value: unknown = raw;
    if (spec.field_type === "number" || spec.field_type === "integer") {
      if (raw === "") {
        value = spec.nullable ? null : undefined;
      } else {
        const parsed = spec.field_type === "integer" ? Number.parseInt(String(raw), 10) : Number(raw);
        value = Number.isNaN(parsed) ? undefined : parsed;
      }
    }
    if (value === undefined) return;
    setDraft(setPath(deepClone(draft), spec.path, value));
  };

  const copyJson = async () => {
    if (!draft) return;
    await navigator.clipboard.writeText(JSON.stringify(draft, null, 2));
    toast.success("已复制当前表单值 JSON");
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
  const maskedTextKey = String(getPath(values, ["models", "annotation", "api_key"]) ?? "");
  const maskedEmbeddingKey = String(getPath(values, ["models", "paragraph_embedding", "api_key"]) ?? "");

  return (
    <div className="mx-auto w-full max-w-4xl space-y-6 px-6 py-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-text">设置</h1>
          <p className="mt-1 text-sm text-text-muted">
            默认值来自代码内置配置，修改项写入 settings.json；模型凭据保存到 .env。保存后立即生效。
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button type="button" variant="outline" onClick={() => setShowJson((v) => !v)}>
            {showJson ? "隐藏 JSON" : "JSON 预览"}
          </Button>
          <Button type="button" onClick={() => (draft ? saveMutation.mutate() : startEditing())} disabled={saveMutation.isPending}>
            {saveMutation.isPending && <Loader2 className="mr-1 h-4 w-4 animate-spin" />}
            {draft ? "保存设置" : "编辑参数"}
          </Button>
        </div>
      </div>

      {isDirty && (
        <div className="rounded-md border border-primary/40 bg-primary-subtle px-4 py-2 text-sm text-text">
          有未保存的修改，保存后立即生效。
        </div>
      )}

      {showJson && draft && (
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="text-base">当前表单值（JSON）</CardTitle>
            <Button type="button" variant="ghost" size="icon" aria-label="复制 JSON" onClick={copyJson}>
              <Copy className="h-4 w-4" />
            </Button>
          </CardHeader>
          <CardContent>
            <Textarea readOnly rows={16} className="font-mono text-xs" value={JSON.stringify(draft, null, 2)} />
          </CardContent>
        </Card>
      )}

      <ProviderCard
        title="文本模型（标注 / 诊断）"
        description="LLM 提供商凭据，保存写入 .env；api_key 留空表示不修改"
        form={textProvider}
        onFormChange={setTextProvider}
        maskedKey={maskedTextKey}
        onTest={() => testMutation.mutate({ task: "annotation", baseUrl: textProvider.base_url })}
        testResult={testResult.annotation}
        testing={testMutation.isPending && testMutation.variables?.task === "annotation"}
      />

      <ProviderCard
        title="嵌入模型（语义检索）"
        description="llama-server 等 OpenAI 兼容嵌入服务；api_key 留空表示不修改"
        form={embeddingProvider}
        onFormChange={setEmbeddingProvider}
        maskedKey={maskedEmbeddingKey}
        onTest={() => testMutation.mutate({ task: "embedding", baseUrl: embeddingProvider.base_url })}
        testResult={testResult.embedding}
        testing={testMutation.isPending && testMutation.variables?.task === "embedding"}
      />

      <Card>
        <CardHeader>
          <CardTitle className="text-base">LTP 模型目录</CardTitle>
          <CardDescription>离线语言结构模型目录（LTP_MODEL_DIR），须为存在的目录</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <FieldRow label="模型目录">
            <Input value={ltpModelDir} onChange={(e) => setLtpModelDir(e.target.value)} placeholder="未配置" />
          </FieldRow>
          <div className="flex justify-end">
            <Button type="button" onClick={() => envMutation.mutate()} disabled={envMutation.isPending}>
              {envMutation.isPending && <Loader2 className="mr-1 h-4 w-4 animate-spin" />}
              保存凭据
            </Button>
          </div>
        </CardContent>
      </Card>

      {sections.map((section) => {
        const sectionFields = fieldsBySection[section.id] ?? [];
        if (sectionFields.length === 0) return null;
        return (
          <Card key={section.id}>
            <CardHeader className="flex flex-row items-start justify-between">
              <div>
                <CardTitle className="text-base">{section.title}</CardTitle>
                <CardDescription>{section.description}</CardDescription>
              </div>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                disabled={!draft}
                onClick={() => resetSection(section.id)}
              >
                <RotateCcw className="mr-1 h-3.5 w-3.5" />
                恢复默认
              </Button>
            </CardHeader>
            <CardContent className="space-y-4">
              {sectionFields.map((spec) => (
                <SettingFieldRow
                  key={spec.path.join("/")}
                  spec={spec}
                  values={draft ?? values}
                  defaults={defaults}
                  sources={sources}
                  editable={Boolean(draft)}
                  onChange={(raw) => updateField(spec, raw)}
                  onReset={() => resetField(spec)}
                />
              ))}
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
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

function FieldRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[180px_1fr] items-center gap-3">
      <span className="text-sm text-text">{label}</span>
      {children}
    </div>
  );
}

interface ProviderCardProps {
  title: string;
  description: string;
  form: ProviderFormState;
  onFormChange: (next: ProviderFormState) => void;
  maskedKey: string;
  onTest: () => void;
  testResult?: string;
  testing?: boolean;
}

function ProviderCard({
  title,
  description,
  form,
  onFormChange,
  maskedKey,
  onTest,
  testResult,
  testing,
}: ProviderCardProps) {
  const configured = maskedKey.startsWith(API_KEY_MASK_PREFIX);
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <FieldRow label="Base URL">
          <Input value={form.base_url} onChange={(e) => onFormChange({ ...form, base_url: e.target.value })} />
        </FieldRow>
        <FieldRow label="模型 ID">
          <Input value={form.model} onChange={(e) => onFormChange({ ...form, model: e.target.value })} />
        </FieldRow>
        <FieldRow label="API Key">
          <div className="flex items-center gap-2">
            <Input
              type="password"
              value={form.api_key}
              onChange={(e) => onFormChange({ ...form, api_key: e.target.value })}
              placeholder={configured ? `已配置（${maskedKey}），留空不修改` : "未配置"}
              autoComplete="new-password"
            />
            <Button type="button" variant="outline" onClick={onTest} disabled={testing}>
              <PlugZap className="mr-1 h-4 w-4" />
              测试连接
            </Button>
          </div>
        </FieldRow>
        {testResult && <p className="text-xs text-text-muted">{testResult}</p>}
      </CardContent>
    </Card>
  );
}

interface SettingFieldRowProps {
  spec: SettingFieldSpec;
  values: Json;
  defaults: Json;
  sources: Record<string, string>;
  editable: boolean;
  onChange: (raw: string | boolean) => void;
  onReset: () => void;
}

function SettingFieldRow({ spec, values, defaults, sources, editable, onChange, onReset }: SettingFieldRowProps) {
  const current = getPath(values, spec.path);
  const defaultValue = getPath(defaults, spec.path);
  const isCustom = sources[spec.path.join("/")] === "file";
  const displayDefault =
    defaultValue === null || defaultValue === undefined ? fieldFallback(spec) : defaultValue;

  return (
    <div className="grid grid-cols-[180px_1fr_auto] items-center gap-3">
      <div>
        <span className="block text-sm text-text">{spec.label}</span>
        {spec.description && <span className="block text-xs text-text-muted">{spec.description}</span>}
      </div>
      <div className="flex items-center gap-2">
        <FieldControl spec={spec} value={current} editable={editable} onChange={onChange} defaultValue={displayDefault} />
        {!spec.editable && <Badge variant="secondary">建库维度</Badge>}
      </div>
      <div className="flex items-center gap-1.5">
        {isCustom && <Badge variant="secondary">已自定义</Badge>}
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label={`恢复默认：${spec.label}`}
          disabled={!editable}
          onClick={onReset}
        >
          <RotateCcw className="h-3.5 w-3.5" />
        </Button>
      </div>
    </div>
  );
}

interface FieldControlProps {
  spec: SettingFieldSpec;
  value: unknown;
  editable: boolean;
  onChange: (raw: string | boolean) => void;
  defaultValue: unknown;
}

function FieldControl({ spec, value, editable, onChange, defaultValue }: FieldControlProps) {
  const className = "max-w-[280px]";
  switch (spec.field_type) {
    case "boolean":
      return (
        <Switch checked={Boolean(value)} disabled={!editable} onCheckedChange={(checked) => onChange(checked)} />
      );
    case "enum": {
      const stringValue = String(value ?? "");
      return (
        <Select value={stringValue} disabled={!editable} onValueChange={(next) => onChange(next)}>
          <SelectTrigger className={className}>
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
          type="number"
          className={className}
          value={text}
          disabled={!editable}
          min={spec.min_value ?? undefined}
          max={spec.max_value ?? undefined}
          step={spec.step ?? (spec.field_type === "integer" ? 1 : undefined)}
          placeholder={`默认 ${String(defaultValue)}`}
          onChange={(e) => onChange(e.target.value)}
        />
      );
    }
      default:
      return (
        <Input
          className={className}
          value={String(value ?? "")}
          disabled={!editable}
          placeholder={`默认 ${String(defaultValue)}`}
          onChange={(e) => onChange(e.target.value)}
        />
      );
  }
}
