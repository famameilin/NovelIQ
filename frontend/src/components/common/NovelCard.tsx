import { useState } from "react";
import {
  MoreVertical,
  BookOpen,
  Trash2,
  Eye,
  Loader2,
  CheckCircle2,
  XCircle,
  Clock,
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
import { AnalysisProgressRing } from "./AnalysisProgressRing";
import { cn } from "@/lib/cn";
import type { TaskStatus } from "@/api/types";

/* ------------------------------------------------------------------ */
/*  Types                                                             */
/* ------------------------------------------------------------------ */

export type NovelStatus = TaskStatus | "pending";

export interface NovelCardData {
  id: string;
  title: string;
  author?: string;
  filename: string;
  fileSize?: number;
  status: NovelStatus;
  progress?: number;
  themeColor?: string;
  updatedAt: string;
  taskId?: string;
}

export interface NovelCardProps {
  novel: NovelCardData;
  onView?: (id: string) => void;
  onDelete?: (id: string) => void;
  className?: string;
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                           */
/* ------------------------------------------------------------------ */

const STATUS_CONFIG: Record<
  NovelStatus,
  {
    label: string;
    variant: "default" | "secondary" | "destructive" | "outline";
    icon: React.ReactNode;
    color: string;
  }
> = {
  pending: {
    label: "待分析",
    variant: "outline",
    icon: <Clock className="h-3 w-3" />,
    color: "hsl(var(--text-muted))",
  },
  chunking: {
    label: "分块中",
    variant: "secondary",
    icon: <Loader2 className="h-3 w-3 animate-spin" />,
    color: "hsl(var(--primary))",
  },
  annotating: {
    label: "标注中",
    variant: "secondary",
    icon: <Loader2 className="h-3 w-3 animate-spin" />,
    color: "hsl(var(--primary))",
  },
  aggregating: {
    label: "聚合中",
    variant: "secondary",
    icon: <Loader2 className="h-3 w-3 animate-spin" />,
    color: "hsl(var(--primary))",
  },
  diagnosing: {
    label: "诊断中",
    variant: "secondary",
    icon: <Loader2 className="h-3 w-3 animate-spin" />,
    color: "hsl(var(--primary))",
  },
  completed: {
    label: "已完成",
    variant: "default",
    icon: <CheckCircle2 className="h-3 w-3" />,
    color: "hsl(var(--chart-positive))",
  },
  failed: {
    label: "失败",
    variant: "destructive",
    icon: <XCircle className="h-3 w-3" />,
    color: "hsl(var(--chart-negative))",
  },
};

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDate(dateString: string): string {
  const date = new Date(dateString);
  
  // 处理无效日期
  if (isNaN(date.getTime())) {
    return "未知时间";
  }
  
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  
  // 处理未来日期（时间戳为负）
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
/*  Component                                                         */
/* ------------------------------------------------------------------ */

export function NovelCard({
  novel,
  onView,
  onDelete,
  className,
}: NovelCardProps) {
  const [imageError, setImageError] = useState(false);
  const statusConfig = STATUS_CONFIG[novel.status];
  const isAnalyzing =
    novel.status !== "completed" &&
    novel.status !== "failed" &&
    novel.status !== "pending";
  const accentColor = novel.themeColor ?? "hsl(var(--primary))";

  return (
    <div
      className={cn(
        // 强制竖向比例 2:3 (宽:高)，这是书籍的比例
        "group relative w-full",
        "aspect-[2/3]",
        className
      )}
      onClick={() => onView?.(novel.id)}
    >
      <Card className="absolute inset-0 flex flex-col overflow-hidden border-0 shadow-md transition-shadow hover:shadow-xl">
        {/* 封面区域 - 占据卡片大部分空间 (75%) */}
        <div className="relative h-[75%] overflow-hidden bg-gradient-to-b from-surface-hover to-surface">
          {/* 左侧主题色装饰边 */}
          <div
            className="absolute left-0 top-0 bottom-0 w-1.5 z-10"
            style={{ backgroundColor: accentColor }}
          />

          {/* 封面图或占位 */}
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
              {/* 装饰几何元素 */}
              <div 
                className="absolute right-4 top-4 h-16 w-16 rounded-full opacity-20"
                style={{ backgroundColor: accentColor }}
              />
              <div 
                className="absolute bottom-6 left-6 h-12 w-12 rounded-lg opacity-15"
                style={{ backgroundColor: accentColor, transform: 'rotate(45deg)' }}
              />
              
              {/* 图标容器 */}
              <div
                className="relative mb-4 flex h-16 w-16 items-center justify-center rounded-2xl shadow-lg"
                style={{ 
                  backgroundColor: `${accentColor}18`,
                  boxShadow: `0 4px 12px ${accentColor}25`
                }}
              >
                <BookOpen className="h-8 w-8" style={{ color: accentColor }} />
              </div>
              
              {/* 标题 - 增大字号提升可读性 */}
              <p className="relative line-clamp-2 text-center text-sm font-semibold text-gray-800 dark:text-gray-200 leading-relaxed">
                {novel.title}
              </p>
            </div>
          )}

          {/* 分析进度遮罩 */}
          {isAnalyzing && (
            <div className="absolute inset-0 flex flex-col items-center justify-center bg-surface/85 backdrop-blur-sm">
              <AnalysisProgressRing
                progress={novel.progress || 0}
                size={44}
                strokeWidth={3}
              />
              <p className="mt-2 text-xs font-medium text-gray-700 dark:text-gray-300">
                {statusConfig.label}
              </p>
            </div>
          )}
        </div>

        {/* 底部信息栏 - 固定高度 (25%) */}
        <div className="flex h-[25%] flex-col justify-between border-t border-border/30 bg-surface p-3">
          <div>
            <h3 className="mb-1 line-clamp-1 text-sm font-semibold text-gray-900 dark:text-gray-100">
              {novel.title}
            </h3>
            <div className="flex items-center gap-2 text-[10px] text-gray-500 dark:text-gray-400">
              {novel.author && (
                <>
                  <span className="line-clamp-1">{novel.author}</span>
                  <span>·</span>
                </>
              )}
              {novel.fileSize && <span>{formatFileSize(novel.fileSize)}</span>}
            </div>
          </div>

          <div className="flex items-center justify-between">
            <Badge
              variant={statusConfig.variant}
              className="h-5 gap-1 px-1.5 text-[10px]"
            >
              {statusConfig.icon}
              {statusConfig.label}
            </Badge>
            <span className="text-[10px] text-gray-500 dark:text-gray-400">
              {formatDate(novel.updatedAt)}
            </span>
          </div>
        </div>

        {/* 操作菜单按钮 */}
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
              <DropdownMenuItem onClick={() => onView?.(novel.id)}>
                <Eye className="mr-2 h-3.5 w-3.5" />
                查看
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                onClick={() => onDelete?.(novel.id)}
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
