/** 把任务失败原因整理成一句摘要，原始内容折叠保留 */

export interface FailureNotice {
  title: string;
  detail?: string;
}

const summaries: Record<number, string> = {
  400: "模型请求参数不被接受", 401: "模型服务鉴权失败", 403: "模型服务拒绝访问",
  404: "模型接口不存在", 408: "模型服务请求超时", 429: "模型服务配额不足或请求受限",
  500: "模型服务内部错误", 502: "模型网关响应异常", 503: "模型服务暂不可用", 504: "模型服务响应超时",
};

const punctuated = (text: string) => (/[。！？.!?]$/.test(text) ? text : `${text}。`);

function firstLine(text: string) {
  const line = text.split(/\r?\n/)[0].trim();
  return line.length > 160 ? `${line.slice(0, 159)}…` : line;
}

function providerMessage(body: string) {
  try {
    const parsed = JSON.parse(body) as { error?: { message?: unknown } };
    if (typeof parsed.error?.message === "string") return parsed.error.message;
  } catch {
    // 非 JSON 的提供方原文按文本提取
  }
  const quoted = /(['"])message\1\s*:\s*\1([\s\S]*?)\1/.exec(body);
  return quoted?.[2]?.trim() || undefined;
}

function describe(status: number, message?: string) {
  const base = summaries[status] ?? "模型服务请求失败";
  const hints: string[] = [];
  if (message && /quota|rate limit|too many requests/i.test(message)) hints.push("用量配额已用尽");
  const reset = message?.match(/reset at ([^.]+?)\./)?.[1]?.trim();
  if (reset) hints.push(`将于 ${reset} 重置`);
  return punctuated(`${base}（HTTP ${status}）${hints.length ? `：${hints.join("，")}，恢复分析前需等待额度恢复` : ""}`);
}

export function failureNotice(raw?: string | null): FailureNotice | null {
  const detail = (raw ?? "").trim();
  if (!detail) return null;
  const match = /^Error code:\s*(\d{3})\s*-\s*([\s\S]*)$/.exec(detail);
  if (!match) return { title: punctuated(firstLine(detail)), detail: detail.includes("\n") ? detail : undefined };
  return { title: describe(Number(match[1]), providerMessage(match[2].trim())), detail };
}
