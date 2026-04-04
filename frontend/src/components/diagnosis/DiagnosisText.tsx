import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/cn";
import { FileText } from "lucide-react";

export interface DiagnosisTextProps {
  /** 诊断文本内容（支持 Markdown） */
  diagnosisText?: string | null;
  className?: string;
}

/**
 * 诊断文本组件 - 展示 LLM 综合诊断文本
 */
export function DiagnosisText({ diagnosisText, className }: DiagnosisTextProps) {
  return (
    <Card variant="elevated" className={cn("rounded-xl overflow-hidden", className)}>
      <CardContent className="flex flex-col gap-3 p-5">
        <div className="flex items-center gap-2">
          <FileText className="h-4 w-4 text-text-muted" />
          <h4 className="text-sm font-semibold text-text">综合诊断</h4>
        </div>

        {diagnosisText ? (
          <div className="prose prose-sm max-w-none prose-p:text-text-muted prose-p:leading-relaxed">
            {diagnosisText.split("\n").map((line, i) => (
              <p key={i} className="mb-2 last:mb-0">
                {line.trim() || <br />}
              </p>
            ))}
          </div>
        ) : (
          <p className="text-sm text-text-muted">暂无诊断文本</p>
        )}
      </CardContent>
    </Card>
  );
}