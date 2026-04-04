import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/cn";

export interface TopicLabelsProps {
  /** 主题标签数组 */
  labels?: string[] | null;
  className?: string;
}

/**
 * 主题标签组件 - 展示小说的主题标签
 */
export function TopicLabels({ labels, className }: TopicLabelsProps) {
  if (!labels || labels.length === 0) {
    return (
      <div className={cn("text-sm text-text-muted", className)}>
        暂无主题标签
      </div>
    );
  }

  return (
    <div className={cn("flex flex-wrap gap-1.5", className)}>
      {labels.map((label, index) => (
        <Badge key={index} variant="secondary" className="text-[10px]">
          {label}
        </Badge>
      ))}
    </div>
  );
}