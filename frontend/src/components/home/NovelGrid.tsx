import { motion, type Variants } from "framer-motion";
import { NovelCard, type NovelCardData } from "@/components/common/NovelCard";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { BookOpen, Upload, ChevronLeft, ChevronRight } from "lucide-react";
import { cn } from "@/lib/cn";

/* ------------------------------------------------------------------ */
/*  Types                                                             */
/* ------------------------------------------------------------------ */

export interface NovelGridProps {
  novels: NovelCardData[];
  isLoading?: boolean;
  onView?: (id: string) => void;
  onDelete?: (id: string) => void;
  onUpload?: () => void;
  page?: number;
  totalPages?: number;
  onPageChange?: (page: number) => void;
  className?: string;
}

/* ------------------------------------------------------------------ */
/*  Animation Variants                                                */
/* ------------------------------------------------------------------ */

const containerVariants: Variants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: {
      staggerChildren: 0.04,
      delayChildren: 0.05,
    },
  },
};

const itemVariants: Variants = {
  hidden: { opacity: 0, y: 12 },
  visible: {
    opacity: 1,
    y: 0,
    transition: {
      duration: 0.3,
      ease: [0.16, 1, 0.3, 1] as const,
    },
  },
};

/* ------------------------------------------------------------------ */
/*  Skeleton Card                                                     */
/* ------------------------------------------------------------------ */

function SkeletonCard() {
  return (
    <Card className="flex h-full flex-col overflow-hidden border-border">
      <div className="min-h-0 flex-1 animate-pulse bg-surface-hover" />
      <div className="shrink-0 space-y-3 p-4">
        <div className="h-5 w-3/4 animate-pulse rounded bg-surface-hover" />
        <div className="h-4 w-1/2 animate-pulse rounded bg-surface-hover" />
        <div className="flex items-center justify-between pt-2">
          <div className="h-6 w-16 animate-pulse rounded-full bg-surface-hover" />
          <div className="h-4 w-20 animate-pulse rounded bg-surface-hover" />
        </div>
      </div>
    </Card>
  );
}

/* ------------------------------------------------------------------ */
/*  Empty State                                                       */
/* ------------------------------------------------------------------ */

function EmptyState({ onUpload }: { onUpload?: () => void }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="flex flex-1 flex-col items-center justify-center"
    >
      <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-primary-subtle">
        <BookOpen className="h-8 w-8 text-primary" />
      </div>

      <h3 className="mb-1 text-lg font-semibold text-text">还没有小说</h3>

      <p className="mb-6 max-w-sm text-center text-sm text-text-secondary">
        上传中文网络小说，开始探索叙事结构、情感走向和人物关系。
      </p>

      {onUpload && (
        <Button size="sm" onClick={onUpload} className="gap-2">
          <Upload className="h-4 w-4" />
          上传小说
        </Button>
      )}
    </motion.div>
  );
}

/* ------------------------------------------------------------------ */
/*  Pagination                                                        */
/* ------------------------------------------------------------------ */

function Pagination({
  page,
  totalPages,
  onPageChange,
}: {
  page: number;
  totalPages: number;
  onPageChange: (page: number) => void;
}) {
  if (totalPages <= 1) return null;

  return (
    <div className="flex shrink-0 items-center justify-center gap-2 pt-6">
      <Button
        variant="ghost"
        size="sm"
        disabled={page <= 1}
        onClick={() => onPageChange(page - 1)}
        className="gap-1"
      >
        <ChevronLeft className="h-4 w-4" />
        上一页
      </Button>

      <span className="min-w-[5rem] text-center text-sm text-gray-600 dark:text-gray-400">
        {page} / {totalPages}
      </span>

      <Button
        variant="ghost"
        size="sm"
        disabled={page >= totalPages}
        onClick={() => onPageChange(page + 1)}
        className="gap-1"
      >
        下一页
        <ChevronRight className="h-4 w-4" />
      </Button>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Main Component                                                    */
/* ------------------------------------------------------------------ */

export function NovelGrid({
  novels,
  isLoading = false,
  onView,
  onDelete,
  onUpload,
  page = 1,
  totalPages = 1,
  onPageChange,
  className,
}: NovelGridProps) {
  // 加载状态
  if (isLoading) {
    return (
      <div className={cn("flex h-full flex-col", className)}>
        <div className="grid h-full grid-cols-3 gap-4 sm:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6">
          {Array.from({ length: 12 }).map((_, i) => (
            <SkeletonCard key={i} />
          ))}
        </div>
      </div>
    );
  }

  // 空状态
  if (novels.length === 0) {
    return <EmptyState onUpload={onUpload} />;
  }

  // 正常列表 - 横向滚动书架布局
  return (
    <div className={cn("flex h-full flex-col", className)}>
      <motion.div
        variants={containerVariants}
        initial="hidden"
        animate="visible"
        key={page}
        className="grid h-full auto-rows-fr grid-cols-3 gap-4 sm:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6"
      >
        {novels.map((novel, index) => (
          <motion.div
            key={`${novel.id}-${index}`}
            variants={itemVariants}
            className="h-full"
          >
            <NovelCard
              novel={novel}
              onView={onView}
              onDelete={onDelete}
            />
          </motion.div>
        ))}
      </motion.div>

      {onPageChange && (
        <Pagination
          page={page}
          totalPages={totalPages}
          onPageChange={onPageChange}
        />
      )}
    </div>
  );
}

export default NovelGrid;
