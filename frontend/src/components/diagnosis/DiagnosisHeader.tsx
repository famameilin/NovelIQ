import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/cn";

export interface DiagnosisHeaderProps {
  /** 稳定题材标签 */
  genreLabels?: string[] | null;
  /** 叙事风格标签 */
  styleLabels?: string[] | null;
  /** 弧线类型 */
  arcType?: string | null;
  className?: string;
}

/**
 * 诊断头部 - 展示题材、风格和弧线类型标签
 *
 * 2026-09-25：本组件直接作 h-full 网格项使用，默认 stretch 会把行高分给 flex 行、
 * 徽章被拉成竖长胶囊/椭圆——self-start + content-start 让徽章恒贴内容高度。
 */
export function DiagnosisHeader({
  genreLabels,
  styleLabels,
  arcType,
  className,
}: DiagnosisHeaderProps) {
  const hasData =
    (genreLabels && genreLabels.length > 0) ||
    (styleLabels && styleLabels.length > 0) ||
    arcType;

  if (!hasData) {
    return null;
  }

  return (
    <div className={cn("flex flex-wrap content-start gap-2 self-start", className)}>
      {genreLabels?.map((label) => (
        <Badge key={`genre-${label}`} variant="secondary" className="text-xs">
          {label}
        </Badge>
      ))}
      {styleLabels?.map((label) => (
        <Badge key={`style-${label}`} variant="outline" className="text-xs">
          {label}
        </Badge>
      ))}
      {arcType && (
        <Badge variant="outline" className="text-xs">
          {arcType}
        </Badge>
      )}
    </div>
  );
}
