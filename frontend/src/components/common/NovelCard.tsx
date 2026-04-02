import { useState } from "react";
import { motion } from "framer-motion";
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
    icon: <Clock className="h-3.5 w-3.5" />,
    color: "hsl(var(--text-muted))",
  },
  chunking: {
    label: "分块中",
    variant: "secondary",
    icon: <Loader2 className="h-3.5 w-3.5 animate-spin" />,
    color: "hsl(var(--primary))",
  },
  annotating: {
    label: "标注中",
    variant: "secondary",
    icon: <Loader2 className="h-3.5 w-3.5 animate-spin" />,
    color: "hsl(var(--primary))",
  },
  aggregating: {
    label: "聚合中",
    variant: "secondary",
    icon: <Loader2 className="h-3.5 w-3.5 animate-spin" />,
    color: "hsl(var(--primary))",
  },
  diagnosing: {
    label: "诊断中",
    variant: "secondary",
    icon: <Loader2 className="h-3.5 w-3.5 animate-spin" />,
    color: "hsl(var(--primary))",
  },
  completed: {
    label: "已完成",
    variant: "default",
    icon: <CheckCircle2 className="h-3.5 w-3.5" />,
    color: "hsl(var(--chart-positive))",
  },
  failed: {
    label: "失败",
    variant: "destructive",
    icon: <XCircle className="h-3.5 w-3.5" />,
    color: "hsl(var(--chart-negative))",
  },
};

function formatDate(dateString: string): string {
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
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

  // 默认使用主色作为主题色
  const accentColor = novel.themeColor ?? "hsl(var(--primary))";

  const handleView = () => onView?.(novel.id);
  const handleDelete = () => {
    if (confirm(`确定要删除《${novel.title}》吗？`)) {
      onDelete?.(novel.id);
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className={className}
    >
      <Card
        variant="elevated"
        className="group relative overflow-hidden cursor-pointer"
        onClick={handleView}
      >
        {/* 顶部主题色装饰条 */}
        <div
          className="absolute left-0 right-0 top-0 h-1"
          style={{ backgroundColor: accentColor }}
        />

        {/* 操作菜单 */}
        <div className="absolute right-3 top-3 z-10">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                className="flex h-8 w-8 items-center justify-center rounded-full bg-surface/80 opacity-0 backdrop-blur-sm transition-all hover:bg-surface-hover group-hover:opacity-100"
                onClick={(e) => e.stopPropagation()}
              >
                <MoreVertical className="h-4 w-4 text-text-secondary" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-40">
              <DropdownMenuItem onClick={handleView}>
                <Eye className="mr-2 h-4 w-4" />
                查看详情
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                onClick={handleDelete}
                className="text-[hsl(var(--chart-negative))]"
              >
                <Trash2 className="mr-2 h-4 w-4" />
                删除
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>

        {/* 封面/占位区域 */}
        <div className="relative aspect-[3/4] overflow-hidden bg-surface-hover">
          {!imageError ? (
            <img
              src={`/api/novels/${novel.id}/cover`}
              alt={novel.title}
              className="h-full w-full object-cover transition-transform duration-500 group-hover:scale-105"
              onError={() => setImageError(true)}
            />
          ) : (
            <div className="flex h-full flex-col items-center justify-center p-6 text-center">
              <div
                className="mb-4 flex h-16 w-16 items-center justify-center rounded-2xl"
                style={{ backgroundColor: `${accentColor}20` }}
              >
                <BookOpen
                  className="h-8 w-8"
                  style={{ color: accentColor }}
                />
              </div>
              <p className="text-sm font-medium text-text line-clamp-2">
                {novel.title}
              </p>
              {novel.author && (
                <p className="mt-1 text-xs text-text-muted">{novel.author}</p>
              )}
            </div>
          )}

          {/* 分析中进度覆盖层 */}
          {isAnalyzing && (
            <div className="absolute inset-0 flex flex-col items-center justify-center bg-surface/80 backdrop-blur-sm">
              <AnalysisProgressRing
                progress={novel.progress || 0}
                size={64}
                strokeWidth={5}
              />
              <p className="mt-3 text-sm font-medium text-text">
                {statusConfig.label}
              </p>
            </div>
          )}
        </div>

        {/* 底部信息区域 */}
        <div className="p-4">
          <div className="mb-3">
            <h3 className="font-semibold text-text line-clamp-1">
              {novel.title}
            </h3>
            {novel.author && (
              <p className="text-sm text-text-muted">{novel.author}</p>
            )}
          </div>

          <div className="flex items-center justify-between">
            <Badge
              variant={statusConfig.variant}
              className="flex items-center gap-1"
            >
              {statusConfig.icon}
              {statusConfig.label}
            </Badge>
            <span className="text-xs text-text-muted">
              {formatDate(novel.updatedAt)}
            </span>
          </div>
        </div>
      </Card>
    </motion.div>
  );
}
