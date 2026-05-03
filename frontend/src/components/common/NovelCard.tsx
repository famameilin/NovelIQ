import { useState } from "react";
import {
  MoreVertical,
  BookOpen,
  Trash2,
  Eye,
} from "lucide-react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/cn";

/* ------------------------------------------------------------------ */
/*  类型定义                                                           */
/* ------------------------------------------------------------------ */

export interface NovelCardData {
  id: string;
  title: string;
  author?: string;
  filename: string;
  fileSize?: number;
  themeColor?: string;
  updatedAt: string;
}

export interface NovelCardProps {
  novel: NovelCardData;
  onView?: (id: string) => void;
  onDelete?: (id: string) => void;
  onPrefetch?: (id: string) => void;
  className?: string;
}

/* ------------------------------------------------------------------ */
/*  辅助函数                                                           */
/* ------------------------------------------------------------------ */

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDate(dateString: string): string {
  const date = new Date(dateString);

  if (isNaN(date.getTime())) {
    return "未知时间";
  }

  const now = new Date();
  const diffMs = now.getTime() - date.getTime();

  if (diffMs < 0) {
    return date.toLocaleDateString("zh-CN");
  }

  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) return "刚刚";
  if (diffMins < 60) return `${diffMins}分钟前`;
  if (diffHours < 24) return `${diffHours}小时前`;
  if (diffDays < 7) return `${diffDays}天前`;
  return date.toLocaleDateString("zh-CN");
}

/* ------------------------------------------------------------------ */
/*  组件主体                                                           */
/* ------------------------------------------------------------------ */

export function NovelCard({
  novel,
  onView,
  onDelete,
  onPrefetch,
  className,
}: NovelCardProps) {
  const [imageError, setImageError] = useState(false);
  const accentColor = novel.themeColor ?? "hsl(var(--primary))";

  return (
    <div
      className={cn(
        "group relative w-full",
        "aspect-[2/3]",
        className
      )}
      onClick={() => onView?.(novel.id)}
      onMouseEnter={() => onPrefetch?.(novel.id)}
    >
      <Card className="absolute inset-0 flex flex-col overflow-hidden border-0 shadow-md transition-shadow hover:shadow-xl">
        <div className="relative h-[75%] overflow-hidden bg-gradient-to-b from-surface-hover to-surface">
          <div
            className="absolute left-0 top-0 bottom-0 w-1.5 z-10"
            style={{ backgroundColor: accentColor }}
          />

          {!imageError ? (
            <img
              src={`/api/novels/${novel.id}/cover`}
              alt={novel.title}
              className="h-full w-full object-cover"
              onError={() => setImageError(true)}
            />
          ) : (
            <div
              className="relative flex h-full flex-col items-center justify-center p-4"
              style={{
                background: `linear-gradient(135deg, ${accentColor}08 0%, ${accentColor}15 50%, ${accentColor}08 100%)`
              }}
            >
              <div
                className="absolute right-4 top-4 h-16 w-16 rounded-full opacity-20"
                style={{ backgroundColor: accentColor }}
              />
              <div
                className="absolute bottom-6 left-6 h-12 w-12 rounded-lg opacity-15"
                style={{ backgroundColor: accentColor, transform: 'rotate(45deg)' }}
              />

              <div
                className="relative mb-4 flex h-16 w-16 items-center justify-center rounded-2xl shadow-lg"
                style={{
                  backgroundColor: `${accentColor}18`,
                  boxShadow: `0 4px 12px ${accentColor}25`
                }}
              >
                <BookOpen className="h-8 w-8" style={{ color: accentColor }} />
              </div>

              <p className="relative line-clamp-2 text-center text-sm font-semibold text-text leading-relaxed">
                {novel.title}
              </p>
            </div>
          )}
        </div>

        <div className="flex h-[25%] flex-col justify-center gap-4 border-t border-border/30 bg-surface px-3 py-2">
          <div className="flex items-start justify-between gap-2">
            <p className="flex-1 text-sm font-semibold text-text truncate">
              {novel.title}
            </p>
            <Badge variant="secondary" className="h-5 text-[10px] px-1.5 shrink-0">
              {novel.fileSize ? formatFileSize(novel.fileSize) : ""}
            </Badge>
          </div>

          <div className="flex items-center justify-between">
            <p className="text-xs text-text-muted truncate max-w-[60%]">
              {novel.author || "未知作者"}
            </p>
            <span className="text-[10px] text-text-muted">
              {formatDate(novel.updatedAt)}
            </span>
          </div>
        </div>

        <div className="absolute right-2 top-2 z-20">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                className="flex h-6 w-6 items-center justify-center rounded-full bg-surface/80 opacity-0 shadow-sm backdrop-blur-sm transition-all hover:bg-surface group-hover:opacity-100"
                onClick={(e) => e.stopPropagation()}
              >
                <MoreVertical className="h-3 w-3 text-text-secondary" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-32">
              <DropdownMenuItem onClick={(e) => {
                e.stopPropagation();
                onView?.(novel.id);
              }}>
                <Eye className="mr-2 h-3.5 w-3.5" />
                查看
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                onClick={(e) => {
                  e.stopPropagation();
                  onDelete?.(novel.id);
                }}
                className="text-destructive"
              >
                <Trash2 className="mr-2 h-3.5 w-3.5" />
                删除
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </Card>
    </div>
  );
}

export default NovelCard;
