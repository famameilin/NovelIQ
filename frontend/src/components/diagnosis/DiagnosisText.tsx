import { DashboardCardShell } from "@/components/common/DashboardCardShell";
import { cn } from "@/lib/cn";
import { FileText } from "lucide-react";
import { DiagnosisPagedText } from "./DiagnosisPagedText";

export interface DiagnosisTextProps {
  /** 诊断文本内容（支持 Markdown） */
  diagnosisText?: string | null;
  className?: string;
  title?: string;
  textClassName?: string;
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
 * 长正文根据卡片实际尺寸分页，保留完整文字及桌面单屏边界
 */
export function DiagnosisText({ diagnosisText, className, title = "综合诊断", textClassName }: DiagnosisTextProps) {
  const formattedDiagnosisText = diagnosisText ? formatDiagnosisText(diagnosisText) : null;

  return (
    <DashboardCardShell
      title={title}
      icon={<FileText className="h-4 w-4" />}
      accent="primary"
      showOrb
      className={cn(className)}
      contentClassName="min-h-0 [&>div:first-child]:shrink-0"
      bodyClassName="min-h-0 flex-1"
    >
      <DiagnosisPagedText key={formattedDiagnosisText} text={formattedDiagnosisText} label={title} emptyText="暂无诊断文本" testId="diagnosis-passage" className={textClassName} />
    </DashboardCardShell>
  );
}
