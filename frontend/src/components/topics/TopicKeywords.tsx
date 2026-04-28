/**
 * TopicKeywords - 关键词标签展示组件
 *
 * 将关键词列表渲染为 Badge 标签组，超出 maxVisible 部分折叠到 Tooltip 中展示
 */
import { motion } from "framer-motion";
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

  const containerVariants = {
    hidden: { opacity: 0 },
    visible: {
      opacity: 1,
      transition: {
        staggerChildren: 0.03,
      },
    },
  };

  const itemVariants = {
    hidden: { opacity: 0, scale: 0.8 },
    visible: { opacity: 1, scale: 1 },
  };

  return (
    <motion.div
      className={cn("flex flex-wrap gap-1", className)}
      variants={containerVariants}
      initial="hidden"
      animate="visible"
    >
      {visibleWords.map((word, index) => (
        <motion.div key={`${word}-${index}`} variants={itemVariants}>
          <Badge
            variant={index < 3 ? "default" : "secondary"}
            className="text-xs"
          >
            {word}
          </Badge>
        </motion.div>
      ))}

      {remainingCount > 0 && (
        <Tooltip>
          <TooltipTrigger asChild>
            <motion.div variants={itemVariants}>
              <Badge variant="outline" className="text-xs cursor-help">
                +{remainingCount}
              </Badge>
            </motion.div>
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
    </motion.div>
  );
}
