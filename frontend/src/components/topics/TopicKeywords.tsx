/**
 * TopicKeywords - 关键词标签展示组件
 *
 * 将关键词列表渲染为 Badge 标签组，超出 maxVisible 部分折叠到 Tooltip 中展示
 */
import { Badge } from "@/components/ui/badge";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/cn";

export interface TopicKeywordsProps {
  words: string[];
  maxVisible?: number;
  className?: string;
}

export function TopicKeywords({
  words,
  maxVisible = 5,
  className,
}: TopicKeywordsProps) {
  if (!words || words.length === 0) {
    return (
      <span className="text-sm text-text-muted">暂无关键词</span>
    );
  }

  const visibleWords = words.slice(0, maxVisible);
  const remainingCount = words.length - maxVisible;
  const remainingWords = words.slice(maxVisible);

  return (
    <div className={cn("flex flex-wrap gap-1", className)}>
      {visibleWords.map((word, index) => (
        <div key={`${word}-${index}`}>
          <Badge
            variant={index < 3 ? "default" : "secondary"}
            className="text-xs"
          >
            {word}
          </Badge>
        </div>
      ))}

      {remainingCount > 0 && (
        <Tooltip>
          <TooltipTrigger asChild>
            <div>
              <Badge variant="outline" className="text-xs cursor-help">
                +{remainingCount}
              </Badge>
            </div>
          </TooltipTrigger>
          <TooltipContent
            side="bottom"
            className="max-w-xs bg-surface border border-border shadow-lg"
          >
            <div className="flex flex-wrap gap-1 p-1">
              {remainingWords.map((word, index) => (
                <Badge
                  key={`${word}-remaining-${index}`}
                  variant="secondary"
                  className="text-xs"
                >
                  {word}
                </Badge>
              ))}
            </div>
          </TooltipContent>
        </Tooltip>
      )}
    </div>
  );
}
