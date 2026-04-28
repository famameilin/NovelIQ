import { DashboardCardShell } from "@/components/common/DashboardCardShell";
import { cn } from "@/lib/cn";
import { FileText } from "lucide-react";

export interface DiagnosisTextProps {
  /** 诊断文本内容（支持 Markdown） */
  diagnosisText?: string | null;
  className?: string;
}

/**
 * 2026-04-21，任务：多页面卡片风格统一
 * 修改原因：统一诊断报告页文本卡片的容器视觉，和仪表盘卡片维持同一套 accent 语言
 *
 * 2026-04-28，任务：分析详情页单屏 Tabs 改造
 * 修改原因：长诊断正文进入单屏工作区后不再额外包滚动壳，溢出直接暴露布局问题
 */
export function DiagnosisText({ diagnosisText, className }: DiagnosisTextProps) {
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
      {diagnosisText ? (
        <div className="min-h-[180px] flex-1 overflow-hidden rounded-2xl border border-border/60 bg-surface/70 p-4 prose prose-sm max-w-none prose-p:text-text-muted prose-p:leading-relaxed">
          {diagnosisText.split("\n").map((line, i) => (
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
