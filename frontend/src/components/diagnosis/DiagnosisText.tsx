import { DashboardCardShell } from "@/components/common/DashboardCardShell";
import { cn } from "@/lib/cn";
import { FileText } from "lucide-react";

export interface DiagnosisTextProps {
  /** 诊断文本内容（支持 Markdown） */
  diagnosisText?: string | null;
  className?: string;
}

const DIAGNOSIS_TEXT_REPLACEMENTS: ReadonlyArray<readonly [RegExp, string]> = [
  [/\bpayoff_likelihood\s*=\s*high\b/gi, "回收可能性较高"],
  [/\bpayoff_likelihood\s*=\s*medium\b/gi, "回收可能性中等"],
  [/\bpayoff_likelihood\s*=\s*low\b/gi, "回收可能性较低"],
  [/\brhythm_avg\b/gi, "平均节奏"],
  [/\bstd\b/gi, "标准差"],
  [/\blikely_paid_off\b/gi, "疑似回收"],
  [/\breinforced\b/gi, "持续强化"],
  [/\barchived\b/gi, "已归档"],
  [/\bopen\b/gi, "待回收"],
];

/**
 * 2026-08-31，作用：将诊断正文中的协议枚举和指标键转换为中文
 * 简要说明：只替换已知技术标记，保留作品名和其他自由文本
 */
function formatDiagnosisText(text: string): string {
  return DIAGNOSIS_TEXT_REPLACEMENTS.reduce(
    (formattedText, [pattern, replacement]) => formattedText.replace(pattern, replacement),
    text,
  );
}

/**
 * 2026-04-21，任务：多页面卡片风格统一
 * 修改原因：统一诊断报告页文本卡片的容器视觉，和仪表盘卡片维持同一套 accent 语言
 *
 * 2026-04-28，任务：分析详情页单屏 Tabs 改造
 * 修改原因：长诊断正文进入单屏工作区后不再额外包滚动壳，溢出直接暴露布局问题
 */
export function DiagnosisText({ diagnosisText, className }: DiagnosisTextProps) {
  const formattedDiagnosisText = diagnosisText ? formatDiagnosisText(diagnosisText) : null;

  return (
    <DashboardCardShell
      title="综合诊断"
      icon={<FileText className="h-4 w-4" />}
      accent="primary"
      showOrb
      className={cn(className)}
      contentClassName="flex h-full flex-col"
      bodyClassName="min-h-0 flex-1 gap-3"
    >
      {formattedDiagnosisText ? (
        <div className="min-h-[180px] flex-1 rounded-lg border border-border/60 bg-surface/70 p-4 prose prose-sm max-w-none prose-p:text-text-muted prose-p:leading-relaxed">
          {formattedDiagnosisText.split("\n").map((line, i) => (
            <p key={i} className="mb-2 last:mb-0">
              {line.trim() || <br />}
            </p>
          ))}
        </div>
      ) : (
        <p className="text-sm text-text-muted">暂无诊断文本</p>
      )}
    </DashboardCardShell>
  );
}
